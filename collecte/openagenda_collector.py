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

import aiohttp

API = os.getenv("OA_API", "https://api.openagenda.com/v2")   # secours : API locale, voir secours/README.md
log = logging.getLogger("openagenda")


async def get_json(session: aiohttp.ClientSession, sem: asyncio.Semaphore, url: str, params) -> dict:
    # TODO : requête GET avec retries (429, 5xx, timeouts) et backoff, comme au TP3
    raise NotImplementedError


async def agenda_uid(session, sem, slug: str) -> int:
    # TODO : retrouver l'uid de l'agenda à partir de son slug
    raise NotImplementedError


async def collect_window(session, sem, uid: int, gte: str, lt: str, queue: asyncio.Queue) -> int:
    # TODO : suivre le curseur "after" jusqu'à la dernière page, pousser chaque événement dans la queue
    raise NotImplementedError


async def main(a) -> None:
    key = os.environ["OA_KEY"]
    async with aiohttp.ClientSession(headers={"key": key}, timeout=aiohttp.ClientTimeout(total=60)) as session:
        # TODO : uid, fenêtres mensuelles en parallèle (TaskGroup), écrivain JSONL
        ...


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--slug", default="rouen-normandie-metropole")
    p.add_argument("--start", default="2024-01")
    p.add_argument("--end", default="2026-11")
    p.add_argument("--out", default="evenements_bruts.jsonl")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(p.parse_args()))
