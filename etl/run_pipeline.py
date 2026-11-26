
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from transform.clean_events import load_jsonl, run, to_postgres
from etl.quality import check_quality


def configure_logging() -> None:
    Path("logs").mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/etl.log", encoding="utf-8"),
        ],
        force=True,
    )


def save_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pipeline ETL des événements OpenAgenda"
    )
    parser.add_argument("--input", default="evenements_bruts.jsonl")
    parser.add_argument("--referentiel", default="data/referentiel_ban.json")
    parser.add_argument("--no-load", action="store_true")
    args = parser.parse_args()

    started_at = time.perf_counter()
    load_dotenv()
    configure_logging()

    logger = logging.getLogger("etl")
    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "failed",
    }

    try:
        logger.info("Début du pipeline ETL")

        logger.debug("Fichier source utilisé : %s", args.input)
        raw_events = load_jsonl(args.input)

        with open(args.referentiel, encoding="utf-8") as file:
            referentiel = json.load(file)

        logger.debug(
            "Référentiel BAN chargé : %s lieux",
            len(referentiel),
        )
        logger.info("%s événements bruts chargés", len(raw_events))

        result = run(raw_events, referentiel)
        events = result["events"]
        rejected = result["rejected"]

        logger.info(
            "Nettoyage terminé : %s événements conservés, %s rejetés",
            len(events),
            len(rejected),
        )

        quality = check_quality(events, rejected)

        if quality["warnings"]:
            logger.warning(
                "%s avertissements détectés lors des contrôles qualité",
                len(quality["warnings"]),
            )

        report["collection_cleaning"] = result["stats"]
        report["quality"] = quality

        save_jsonl("quarantaine_evenements.jsonl", rejected)
        logger.info("%s lignes enregistrées en quarantaine", len(rejected))

        if not quality["passed"]:
            logger.error("Les contrôles qualité ont échoué")
            raise RuntimeError("Les contrôles qualité ont échoué")

        logger.info("Contrôles qualité réussis")

        if not args.no_load:
            dsn = os.getenv("PG_DSN")
            if not dsn:
                raise RuntimeError(
                    "Variable PG_DSN absente du fichier .env"
                )

            to_postgres(events, dsn)
            logger.info("Chargement PostgreSQL terminé")
        else:
            logger.info("Mode sans chargement PostgreSQL")

        report["status"] = "success"

    except Exception:
        logger.exception("Échec du pipeline ETL")
        report["error"] = "Échec du pipeline, consulter logs/etl.log"

    finally:
        report["duration_seconds"] = round(
            time.perf_counter() - started_at, 2
        )
        report["finished_at"] = datetime.now(timezone.utc).isoformat()

        Path("run_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("Rapport enregistré dans run_report.json")

    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
