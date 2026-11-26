
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import psycopg
from dotenv import load_dotenv
from huggingface_hub import HfApi
from psycopg.rows import dict_row


REPO_ID = "Axel229/fil-rouge-sql-metropole"

QUERIES = {
    "events": """
        SELECT
            e.event_uid, e.title, e.description, e.keywords, e.status,
            v.name AS venue_name, v.address AS venue_address,
            v.city, v.lat, v.lon
        FROM events e
        LEFT JOIN venues v ON v.venue_id = e.venue_id
        ORDER BY e.event_uid
    """,
    "occurrences": """
        SELECT
            eo.event_uid, e.title, eo.begin_ts, eo.end_ts
        FROM event_occurrences eo
        JOIN events e ON e.event_uid = eo.event_uid
        ORDER BY eo.event_uid, eo.begin_ts
    """,
    "indices": """
        SELECT
            i.event_uid, e.title, e.status,
            v.name AS venue_name, v.city,
            i.begin_ts, o.end_ts, i.counter_id,
            i.observe, i.attendu, i.nb_semaines, i.indice,
            c.categorie AS coverage_category
        FROM v_indice_evenement i
        JOIN events e ON e.event_uid = i.event_uid
        LEFT JOIN venues v ON v.venue_id = e.venue_id
        LEFT JOIN event_occurrences o
            ON o.event_uid = i.event_uid
            AND o.begin_ts = i.begin_ts
        LEFT JOIN v_couverture c ON c.event_uid = i.event_uid
        ORDER BY i.event_uid, i.begin_ts, i.counter_id
    """,
    "coverage": """
        SELECT
            c.event_uid, e.title, e.status,
            v.name AS venue_name, v.city,
            c.categorie AS coverage_category
        FROM v_couverture c
        JOIN events e ON e.event_uid = c.event_uid
        LEFT JOIN venues v ON v.venue_id = e.venue_id
        ORDER BY c.event_uid
    """,
}


def export_table(
    cursor: psycopg.Cursor,
    name: str,
    query: str,
    output_dir: Path,
) -> int:
    logging.info("Extraction de %s...", name)
    cursor.execute(query)
    rows = cursor.fetchall()

    table = pa.Table.from_pylist(rows)
    output_path = output_dir / f"{name}.parquet"

    pq.write_table(table, output_path, compression="zstd")

    logging.info("%s : %s lignes exportées", name, len(rows))
    return len(rows)


def publish_dataset(output_dir: Path) -> None:
    token = os.getenv("HF_TOKEN")
    if not token:
        raise RuntimeError("Variable HF_TOKEN absente du fichier .env")

    api = HfApi(token=token)

    logging.info("Création ou vérification du dépôt %s", REPO_ID)
    api.create_repo(
        repo_id=REPO_ID,
        repo_type="dataset",
        private=False,
        exist_ok=True,
    )

    logging.info("Publication des fichiers sur Hugging Face...")
    api.upload_folder(
        folder_path=str(output_dir),
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message="Publication initiale du jeu de données v1.0",
    )

    logging.info("Création du tag v1.0...")
    api.create_tag(
        repo_id=REPO_ID,
        tag="v1.0",
        repo_type="dataset",
        revision="main",
        tag_message="Première version du jeu de données",
    )

    logging.info("Publication terminée : https://huggingface.co/datasets/%s", REPO_ID)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export et publication du jeu de données"
    )
    parser.add_argument(
        "--output",
        default="data/hub_export",
        help="Dossier de destination des fichiers Parquet",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publier les fichiers sur Hugging Face",
    )
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    dsn = os.getenv("PG_DSN")
    if not dsn:
        logging.error("Variable PG_DSN absente du fichier .env")
        return 1

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cursor:
                totals = {
                    name: export_table(cursor, name, query, output_dir)
                    for name, query in QUERIES.items()
                }

        logging.info("Export terminé : %s", totals)

        if args.publish:
            publish_dataset(output_dir)
        else:
            logging.info("Mode export uniquement : aucune publication.")

        return 0

    except Exception:
        logging.exception("Échec de l'opération")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
