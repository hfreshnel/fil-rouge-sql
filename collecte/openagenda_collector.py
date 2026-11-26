"""Fil rouge — Collecteur OpenAgenda À COMPLÉTER (créneau fil rouge de la séance 4). RENDU DE GROUPE.

Objectif : récupérer tous les événements de l'agenda de la Métropole sur une période, en JSONL.

Ce que vous savez de l'API (doc : https://developers.openagenda.com) :
  - authentification : en-tête HTTP  key: <votre clé publique>  (compte OpenAgenda gratuit)
  - GET /v2/agendas?slug[]=<slug>               -> {"agendas": [{"uid": ..., ...}]}
  - GET /v2/agendas/{uid}/events?size=100&detailed=1&timings[gte]=...&timings[lte]=...
        -> {"total": N, "events": [...], "after": [...]}
  - page suivante : renvoyer les valeurs de "after" en paramètres répétés  after[]=v1&after[]=v2…

Difficulté : la pagination par curseur est SÉQUENTIELLE. Comment paralléliser quand même ?
Indice : découper la période en fenêtres (une par mois) collectées en parallèle, chacune avec son curseur.

Réutilisez votre collecteur du TP3 : Semaphore, retries + backoff, file asyncio.Queue, écriture par lots.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import calendar
import queue
import aiohttp
from dotenv import load_dotenv

import json
from pathlib import Path

API = os.getenv("OA_API", "https://api.openagenda.com/v2")   # secours : API locale, voir secours/README.md
log = logging.getLogger("openagenda")



async def get_json(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    url: str,
    params
) -> dict:
    """Effectue une requête GET avec retries et backoff exponentiel."""

    max_attempts = 5

    for attempt in range(max_attempts):
        try:
            async with sem:
                async with session.get(url, params=params) as response:

                    # Erreurs temporaires : on pourra réessayer
                    if response.status == 429 or response.status >= 500:
                        retry_after = response.headers.get("Retry-After")
                        await response.read()

                        if attempt == max_attempts - 1:
                            response.raise_for_status()

                        delay = (
                            float(retry_after)
                            if retry_after and retry_after.isdigit()
                            else 2 ** attempt
                        )

                        log.warning(
                            "Erreur HTTP %s sur %s. Nouvelle tentative dans %s s.",
                            response.status,
                            url,
                            delay
                        )

                    else:
                        response.raise_for_status()
                        return await response.json()

            await asyncio.sleep(delay)

        except (aiohttp.ClientError, asyncio.TimeoutError) as error:
            if attempt == max_attempts - 1:
                raise

            delay = 2 ** attempt

            log.warning(
                "Erreur réseau : %s. Nouvelle tentative dans %s s.",
                error,
                delay
            )

            await asyncio.sleep(delay)

    raise RuntimeError(f"Échec de la requête après {max_attempts} tentatives : {url}")




async def agenda_uid(session, sem, slug: str) -> int:
    """Récupère l'UID d'un agenda à partir de son slug."""

    url = f"{API}/agendas"
    params = [("slug[]", slug)]

    data = await get_json(session, sem, url, params)

    agendas = data.get("agendas", [])

    if not agendas:
        raise ValueError(f"Aucun agenda trouvé pour le slug : {slug}")

    uid = agendas[0].get("uid")

    if uid is None:
        raise ValueError(f"UID absent pour l'agenda : {slug}")

    log.info("Agenda trouvé : %s (UID : %s)", slug, uid)

    return int(uid)




async def collect_window(
    session,
    sem,
    uid: int,
    gte: str,
    lt: str,
    queue: asyncio.Queue
) -> int:
    """Collecte toutes les pages d'une fenêtre temporelle."""

    url = f"{API}/agendas/{uid}/events"

    params = [
        ("size", 100),
        ("detailed", 1),
        ("timings[gte]", gte),
        ("timings[lte]", lt),
    ]

    total_collected = 0

    while True:
        data = await get_json(session, sem, url, params)

        events = data.get("events", [])

        for event in events:
            await queue.put(event)

        total_collected += len(events)

        # Récupération du curseur pour la page suivante
        after = data.get("after", [])

        log.info(
            "Fenêtre %s -> %s : %s événements récupérés",
            gte,
            lt,
            total_collected
        )

        if not after:
            break

        # Les curseurs doivent être transmis comme paramètres répétés
        params = [
            ("size", 100),
            ("detailed", 1),
            ("timings[gte]", gte),
            ("timings[lte]", lt),
        ] + [("after[]", cursor) for cursor in after]

    return total_collected



def monthly_windows(start: str, end: str) -> list[tuple[str, str]]:
    """Découpe une période YYYY-MM en fenêtres mensuelles inclusives."""

    start_year, start_month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))

    windows = []

    year, month = start_year, start_month

    while (year, month) <= (end_year, end_month):
        last_day = calendar.monthrange(year, month)[1]

        gte = f"{year:04d}-{month:02d}-01T00:00:00"
        lt = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59"

        windows.append((gte, lt))

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    return windows

def pending_windows(
    windows: list[tuple[str, str]],
    completed: list[str]
) -> list[tuple[str, str]]:
    """Retourne les fenêtres mensuelles qui restent à collecter."""

    completed_set = set(completed)

    return [
        (gte, lt)
        for gte, lt in windows
        if gte[:7] not in completed_set
    ]

def load_checkpoint(path: str, slug: str, start: str, end: str) -> list[str]:
    """Charge le checkpoint uniquement s'il correspond à la collecte."""

    checkpoint = Path(path)

    if not checkpoint.exists():
        return []

    with checkpoint.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if (
        data.get("slug") != slug
        or data.get("start") != start
        or data.get("end") != end
    ):
        log.warning("Checkpoint incompatible : nouvelle collecte.")
        return []

    return data.get("completed_months", [])


def save_checkpoint(
    path: str,
    completed: list[str],
    slug: str,
    start: str,
    end: str
) -> None:
    """Enregistre la progression de la collecte."""

    checkpoint = Path(path)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    temporary = checkpoint.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "slug": slug,
                "start": start,
                "end": end,
                "completed_months": sorted(set(completed))
            },
            file,
            ensure_ascii=False,
            indent=2
        )

    temporary.replace(checkpoint)
async def jsonl_writer(queue: asyncio.Queue, output: str) -> None:
    """Écrit les événements dans un fichier JSONL par lots de 500."""

    batch = []

    with open(output, "w", encoding="utf-8") as file:
        while True:
            event = await queue.get()

            if event is None:
                if batch:
                    for item in batch:
                        import json
                        file.write(json.dumps(item, ensure_ascii=False) + "\n")
                queue.task_done()
                break

            batch.append(event)
            queue.task_done()

            if len(batch) >= 500:
                import json
                for item in batch:
                    file.write(json.dumps(item, ensure_ascii=False) + "\n")

                file.flush()
                log.info("%s événements écrits dans %s", len(batch), output)
                batch.clear()

async def collect_and_save_window(
    session,
    sem,
    uid: int,
    gte: str,
    lt: str,
    output: str,
    checkpoint_path: str,
    completed: list[str],
    checkpoint_lock: asyncio.Lock,
    slug: str,
    start: str,
    end: str
) -> int:
    """Collecte, enregistre et valide une fenêtre mensuelle."""

    temporary_output = output + ".tmp"
    queue = asyncio.Queue(maxsize=1000)

    writer_task = asyncio.create_task(
        jsonl_writer(queue, temporary_output)
    )

    try:
        total = await collect_window(
            session, sem, uid, gte, lt, queue
        )
    finally:
        await queue.put(None)
        await writer_task

    # Le fichier devient définitif uniquement après réussite.
    Path(temporary_output).replace(Path(output))

    async with checkpoint_lock:
        completed.append(gte[:7])

        save_checkpoint(
            checkpoint_path,
            completed,
            slug,
            start,
            end
        )

    return total

def merge_monthly_files(
    windows: list[tuple[str, str]],
    output: str,
    data_dir: str
) -> None:
    """Fusionne les fichiers mensuels dans un fichier JSONL final."""

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary = output_path.with_suffix(".tmp")

    with temporary.open("w", encoding="utf-8") as final_file:
        for gte, _ in windows:
            month = gte[:7]
            monthly_file = Path(data_dir) / f"{month}.jsonl"

            if monthly_file.exists():
                with monthly_file.open("r", encoding="utf-8") as source:
                    for line in source:
                        final_file.write(line)

    temporary.replace(output_path)
async def main(a) -> None:
    load_dotenv()
    key = os.environ["OA_KEY"]

    sem = asyncio.Semaphore(5)
    timeout = aiohttp.ClientTimeout(total=60)

    # Dossier des fichiers mensuels et du checkpoint
    data_dir = Path("data/openagenda")
    data_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = str(data_dir / "checkpoint.json")

    async with aiohttp.ClientSession(
        headers={"key": key},
        timeout=timeout
    ) as session:

        uid = await agenda_uid(session, sem, a.slug)

        # Fenêtres mensuelles demandées
        windows = monthly_windows(a.start, a.end)

        # Reprise : ignorer les mois déjà terminés
        completed = load_checkpoint(
            checkpoint_path,
            a.slug,
            a.start,
            a.end
        )
        pending = pending_windows(windows, completed)

        log.info(
            "%s mois déjà terminés, %s mois à collecter",
            len(completed),
            len(pending)
        )

        checkpoint_lock = asyncio.Lock()
        total = 0

        # Collecte parallèle des mois restants
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(
                    collect_and_save_window(
                        session,
                        sem,
                        uid,
                        gte,
                        lt,
                        str(data_dir / f"{gte[:7]}.jsonl"),
                        checkpoint_path,
                        completed,
                        checkpoint_lock,
                        a.slug,
                        a.start,
                        a.end
                    )
                )
                for gte, lt in pending
            ]

        total = sum(task.result() for task in tasks)

    # Fusion des fichiers mensuels
    merge_monthly_files(windows, a.out, str(data_dir))

    log.info(
        "Collecte terminée : %s nouveaux événements récupérés. Fichier final : %s",
        total,
        a.out
    )



if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--slug", default="rouen-normandie-metropole")
    p.add_argument("--start", default="2024-01")
    p.add_argument("--end", default="2026-11")
    p.add_argument("--out", default="evenements_bruts.jsonl")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(p.parse_args()))
