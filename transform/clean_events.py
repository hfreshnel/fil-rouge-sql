"""Fil rouge — SQUELETTE À COMPLÉTER pour le nettoyage des événements OpenAgenda (créneau fil rouge de la séance 5).

Entrée  : événements bruts collectés (JSONL, un événement OpenAgenda par ligne).
Sortie  : événements propres + occurrences + lieux normalisés ; lignes rejetées en quarantaine avec leur raison.

Règles à implémenter (les tests de tests/test_clean_events.py sont la spécification) :
  - rejet : uid manquant, titre vide, aucune date, toutes les dates incohérentes (fin < début)
  - dédoublonnage : même uid -> on garde la version la plus récente (updatedAt) ;
                    uids différents mais même titre normalisé + même lieu + même première date -> doublon
  - nettoyage : HTML retiré des descriptions, espaces normalisés, mots-clés en minuscules sans doublons
  - lieux : nom normalisé, rapprochement approximatif avec le référentiel des salles (même ville)
  - géolocalisation hors de l'emprise de la Métropole -> mise à NULL (pas un rejet), à géocoder via la BAN
"""
from __future__ import annotations

import difflib
import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
PUNCT_RE = re.compile(r"[^a-z0-9 ]")
STOP_WORDS = {"le", "la", "les", "l", "de", "du", "des", "d", "salle", "espace", "the"}
# Emprise approximative de la Métropole Rouen Normandie
BBOX = {"lat": (49.20, 49.60), "lon": (0.70, 1.35)}
# Codes de statut OpenAgenda -> libellés internes (VÉRIFIER dans la doc développeur OpenAgenda)
STATUS = {1: "programme", 2: "reporte", 3: "en_ligne", 4: "complet", 5: "annule", 6: "annule"}


# ---------- utilitaires ----------
def text_fr(value) -> str | None:
    """Les champs OpenAgenda sont souvent multilingues : {'fr': '...', 'en': '...'}."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("fr") or next((v for v in value.values() if v), None)
    return str(value)


def clean_text(value) -> str:
    # TODO : lire le texte français (text_fr), retirer les balises HTML, décoder les entités, normaliser les espaces
    raise NotImplementedError


def normalize_name(name: str | None) -> str:
    """'Le 106 – Salle des Musiques Actuelles' -> '106 musiques actuelles'."""
    # TODO : minuscules, sans accents (unicodedata), sans ponctuation, sans les mots de STOP_WORDS
    raise NotImplementedError


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def in_bbox(lat, lon) -> bool:
    return (lat is not None and lon is not None
            and BBOX["lat"][0] <= lat <= BBOX["lat"][1] and BBOX["lon"][0] <= lon <= BBOX["lon"][1])


# ---------- structures ----------
@dataclass
class CleanEvent:
    uid: int
    title: str
    description: str
    keywords: list[str]
    status: str
    updated_at: datetime | None
    venue_name: str | None
    venue_norm: str
    city: str | None
    lat: float | None
    lon: float | None
    occurrences: list[tuple[datetime, datetime]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


# ---------- règles ----------
def validate_and_clean(raw: dict) -> tuple[CleanEvent | None, str | None]:
    """Renvoie (événement propre, None) ou (None, raison du rejet)."""
    # TODO : appliquer les règles de rejet, construire un CleanEvent (occurrences triées, statut, mots-clés, flags)
    raise NotImplementedError


def deduplicate(events: list[CleanEvent]) -> tuple[list[CleanEvent], list[dict]]:
    """Doublons par uid (garde le plus récent) puis doublons « métier » entre uids différents."""
    # TODO : 1) même uid -> garder le plus récent (updated_at)  2) même (titre normalisé, lieu normalisé, 1re date) -> doublon
    raise NotImplementedError


def match_venue(venue_norm: str, city: str | None, referentiel: list[dict], seuil: float = 0.85) -> dict | None:
    """Rapprochement approximatif d'un lieu avec le référentiel (même ville si connue)."""
    # TODO : difflib.SequenceMatcher sur les noms normalisés, même ville si connue, None sous le seuil
    raise NotImplementedError


def run(raw_events: list[dict], referentiel: list[dict]) -> dict:
    ok, rejected = [], []
    for raw in raw_events:
        ev, reason = validate_and_clean(raw)
        if reason:
            rejected.append({"reason": reason, "uid": raw.get("uid")})
        else:
            ok.append(ev)
    kept, dup = deduplicate(ok)
    rejected += dup
    matched = 0
    for ev in kept:
        ref = match_venue(ev.venue_norm, ev.city, referentiel)
        if ref:
            matched += 1
            ev.venue_name = ref["name"]
            ev.venue_norm = normalize_name(ref["name"])
            if ev.lat is None and in_bbox(ref.get("lat"), ref.get("lon")):
                ev.lat, ev.lon = ref["lat"], ref["lon"]
                ev.flags.append("geoloc_depuis_referentiel")
    return {"events": kept, "rejected": rejected,
            "stats": {"entree": len(raw_events), "sortie": len(kept), "rejets": len(rejected),
                      "lieux_rapproches": matched,
                      "sans_geoloc": sum(1 for e in kept if e.lat is None)}}


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def to_postgres(events: list[CleanEvent], dsn: str) -> None:
    """Chargement IDEMPOTENT : upsert des lieux et des événements, occurrences remplacées."""
    import psycopg
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for ev in events:
            cur.execute(
                """INSERT INTO venues (name, name_norm, city, lat, lon, source)
                   VALUES (%s, %s, %s, %s, %s, 'openagenda')
                   ON CONFLICT (name_norm, city) DO UPDATE
                     SET lat = COALESCE(venues.lat, EXCLUDED.lat), lon = COALESCE(venues.lon, EXCLUDED.lon)
                   RETURNING venue_id""",
                (ev.venue_name or "(inconnu)", ev.venue_norm or "inconnu", ev.city, ev.lat, ev.lon))
            venue_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO events (event_uid, title, description, keywords, venue_id, status, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (event_uid) DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description,
                     keywords = EXCLUDED.keywords, venue_id = EXCLUDED.venue_id, status = EXCLUDED.status,
                     updated_at = EXCLUDED.updated_at, loaded_at = now()""",
                (ev.uid, ev.title, ev.description, ev.keywords, venue_id, ev.status, ev.updated_at))
            cur.execute("DELETE FROM event_occurrences WHERE event_uid = %s", (ev.uid,))
            cur.executemany("INSERT INTO event_occurrences VALUES (%s, %s, %s)",
                            [(ev.uid, b, e) for b, e in ev.occurrences])
        conn.commit()


if __name__ == "__main__":
    import argparse
    import os
    p = argparse.ArgumentParser()
    p.add_argument("events_jsonl")
    p.add_argument("--referentiel", help="JSON : liste de {name, city, lat, lon}")
    p.add_argument("--load", action="store_true")
    a = p.parse_args()
    ref = json.load(open(a.referentiel, encoding="utf-8")) if a.referentiel else []
    res = run(load_jsonl(a.events_jsonl), ref)
    print(json.dumps(res["stats"], indent=2, ensure_ascii=False))
    with open("quarantaine_evenements.jsonl", "w", encoding="utf-8") as f:
        for r in res["rejected"]:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    if a.load:
        to_postgres(res["events"], os.getenv("PG_DSN", "postgresql://etl:etl@localhost:5432/metropole"))
