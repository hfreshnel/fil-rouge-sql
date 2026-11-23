"""Fil rouge (option) — Collecte périodique des stations Lovélo (flux GBFS) dans PostgreSQL. Fourni.

Le flux GBFS est référencé sur transport.data.gouv.fr (jeu « VLS Lovélo Rouen »). Récupérer l'URL de
gbfs.json sur cette page, puis :
    python lovelo_collector.py --gbfs-url <URL gbfs.json> --every 60

Chaque relevé est inséré une fois : la clé (station_id, reported_at) dédoublonne naturellement
les relevés identiques quand la station n'a pas changé.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone

import aiohttp

DSN = os.getenv("PG_DSN", "postgresql://etl:etl@localhost:5432/metropole")
log = logging.getLogger("lovelo")


async def fetch(session, url):
    async with session.get(url) as r:
        r.raise_for_status()
        return await r.json(content_type=None)


def feed_urls(gbfs: dict) -> dict:
    data = gbfs.get("data", {})
    lang = data.get("fr") or data.get("en") or next(iter(data.values()))
    return {f["name"]: f["url"] for f in lang["feeds"]}


async def snapshot(session, feeds, conn, first: bool):
    if first:
        info = await fetch(session, feeds["station_information"])
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO lovelo_stations VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (station_id) DO UPDATE SET name = EXCLUDED.name, capacity = EXCLUDED.capacity""",
                [(s["station_id"], s.get("name"), s.get("lat"), s.get("lon"), s.get("capacity"))
                 for s in info["data"]["stations"]])
    status = await fetch(session, feeds["station_status"])
    rows = [(s["station_id"], datetime.fromtimestamp(s.get("last_reported") or status["last_updated"], timezone.utc),
             s.get("num_bikes_available"), s.get("num_docks_available"), bool(s.get("is_renting", True)))
            for s in status["data"]["stations"]]
    with conn.cursor() as cur:
        cur.executemany("""INSERT INTO lovelo_status VALUES (%s, %s, %s, %s, %s)
                           ON CONFLICT DO NOTHING""", rows)
    conn.commit()
    log.info("%d stations relevées", len(rows))


async def main(a):
    import psycopg
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        feeds = feed_urls(await fetch(session, a.gbfs_url))
        with psycopg.connect(DSN) as conn:
            first = True
            while True:
                try:
                    await snapshot(session, feeds, conn, first)
                    first = False
                except Exception as e:  # le collecteur ne doit pas s'arrêter sur une erreur ponctuelle
                    log.error("relevé en échec : %s", e)
                await asyncio.sleep(a.every)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gbfs-url", required=True)
    p.add_argument("--every", type=int, default=60, help="secondes entre deux relevés")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s | %(message)s")
    asyncio.run(main(p.parse_args()))
