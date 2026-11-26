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
    """Récupère prioritairement le contenu français."""
    if value is None:
        return None

    if isinstance(value, dict):
        return value.get("fr")

    return str(value)


def clean_text(value) -> str:
    """Nettoie un texte OpenAgenda et conserve la version française."""
    value = text_fr(value)

    if value is None:
        return ""

    value = html.unescape(str(value))
    value = TAG_RE.sub(" ", value)
    value = SPACE_RE.sub(" ", value)

    return value.strip()


def normalize_name(name: str | None) -> str:
    """Normalise un nom de lieu pour faciliter les comparaisons."""
    if not name:
        return ""

    name = str(name).lower()
    name = unicodedata.normalize("NFKD", name)
    name = "".join(
        char for char in name
        if not unicodedata.combining(char)
    )

    name = PUNCT_RE.sub(" ", name)
    words = [
        word for word in SPACE_RE.split(name.strip())
        if word and word not in STOP_WORDS
    ]

    return " ".join(words)


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
    venue_uid: str | None = None
    occurrences: list[tuple[datetime, datetime]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


# ---------- règles ----------

def validate_and_clean(raw: dict) -> tuple[CleanEvent | None, str | None]:
    """Valide et nettoie un événement OpenAgenda."""

    # 1. Vérification de l'identifiant
    uid = raw.get("uid")

    if uid is None or str(uid).strip() == "":
        return None, "uid_manquant"

    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None, "uid_manquant"

    # 2. Nettoyage et validation du titre
    title = clean_text(raw.get("title"))

    if not title:
        return None, "titre_vide"

    # 3. Nettoyage de la description
    description = clean_text(raw.get("description"))

    # 4. Nettoyage des mots-clés
    raw_keywords = text_fr(raw.get("keywords"))
    keywords = []

    if isinstance(raw_keywords, list):
        for keyword in raw_keywords:
            cleaned = clean_text(keyword).lower()

            if cleaned and cleaned not in keywords:
                keywords.append(cleaned)

    keywords.sort()

    # 5. Validation et conversion des dates
    timings = raw.get("timings") or []

    if not timings:
        return None, "aucune_date"

    occurrences = []
    date_incoherente = False

    for timing in timings:
        begin = parse_ts(timing.get("begin"))
        end = parse_ts(timing.get("end"))

        if begin is None or end is None or end < begin:
            date_incoherente = True
            continue

        occurrences.append((begin, end))

    # Si aucune occurrence valide ne reste, rejeter l'événement
    if not occurrences:
        return None, "dates_incoherentes"

    occurrences.sort(key=lambda occurrence: occurrence[0])

    # 6. Récupération du lieu
    location = raw.get("location") or {}

    venue_name = clean_text(location.get("name")) or None
    venue_uid = str(location.get("uid")) if location.get("uid") is not None else None
    venue_norm = normalize_name(venue_name)
    city = clean_text(location.get("city")) or None

    # 7. Vérification des coordonnées géographiques
    lat = location.get("latitude")
    lon = location.get("longitude")

    try:
        lat = float(lat) if lat is not None else None
        lon = float(lon) if lon is not None else None
    except (TypeError, ValueError):
        lat, lon = None, None

    # 8. Gestion des anomalies
    flags = []

    # Signaler les dates incohérentes ignorées
    if date_incoherente:
        flags.append("date_incoherente_ignoree")

    # Les coordonnées absentes ou hors zone sont mises à NULL
    if not in_bbox(lat, lon):
        lat, lon = None, None
        flags.append("geoloc_absente_ou_hors_zone")

    # 9. Récupération du statut et de la date de mise à jour
    status_code = raw.get("status")
    status = STATUS.get(status_code, "inconnu")

    updated_at = parse_ts(raw.get("updatedAt"))

    # 10. Construction de l'événement propre
    event = CleanEvent(
        uid=uid,
        title=title,
        description=description,
        keywords=keywords,
        status=status,
        updated_at=updated_at,
        venue_name=venue_name,
        venue_norm=venue_norm,
        city=city,
        lat=lat,
        lon=lon,
        venue_uid=venue_uid,
        occurrences=occurrences,
        flags=flags
    )

    return event, None


def deduplicate(events: list[CleanEvent]) -> tuple[list[CleanEvent], list[dict]]:
    """Supprime les doublons par UID puis les doublons métier."""

    # Étape 1 : dédoublonnage par UID
    by_uid = {}
    rejected = []

    for event in events:
        if event.uid not in by_uid:
            by_uid[event.uid] = event
            continue

        existing = by_uid[event.uid]

        existing_date = existing.updated_at or datetime.min.replace(tzinfo=timezone.utc)
        new_date = event.updated_at or datetime.min.replace(tzinfo=timezone.utc)

        if new_date > existing_date:
            rejected.append({
                "reason": "doublon_uid",
                "uid": existing.uid
            })
            by_uid[event.uid] = event
        else:
            rejected.append({
                "reason": "doublon_uid",
                "uid": event.uid
            })

    # Étape 2 : dédoublonnage métier
    kept = []
    seen = set()

    for event in by_uid.values():
        first_date = event.occurrences[0][0] if event.occurrences else None

        key = (
            normalize_name(event.title),
            event.venue_norm,
            first_date
        )

        if key in seen:
            rejected.append({
                "reason": "doublon_metier",
                "uid": event.uid
            })
            continue

        seen.add(key)
        kept.append(event)

    return kept, rejected



def match_venue(
    venue_norm: str,
    city: str | None,
    referentiel: list[dict],
    seuil: float = 0.85
) -> dict | None:
    """Rapproche un lieu du référentiel avec une comparaison approximative."""

    if not venue_norm:
        return None

    best_match = None
    best_score = 0.0

    for venue in referentiel:
        ref_name = normalize_name(venue.get("name"))

        if not ref_name:
            continue

        # Si la ville est connue, on privilégie les lieux de cette ville
        ref_city = venue.get("city")

        if city and ref_city:
            if city.strip().lower() != ref_city.strip().lower():
                continue

        score = difflib.SequenceMatcher(
            None,
            venue_norm,
            ref_name
        ).ratio()

        if score > best_score:
            best_score = score
            best_match = venue

    if best_score >= seuil:
        return best_match

    return None



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
        # 1. Recherche prioritaire par identifiant OpenAgenda
        ref = next(
            (
                v for v in referentiel
                if ev.venue_uid is not None
                and str(v.get("openagenda_uid")) == ev.venue_uid
            ),
            None
        )

        # 2. Ancien mécanisme de rapprochement par nom et ville
        if ref is None:
            ref = match_venue(ev.venue_norm, ev.city, referentiel)

        # 3. Traitement du lieu trouvé
        if ref:
            matched += 1

            ev.venue_name = ref["name"]
            ev.venue_norm = normalize_name(ref["name"])

            ref_lat = ref.get("lat")
            ref_lon = ref.get("lon")

            # Pour le référentiel BAN, seules les coordonnées
            # ayant le statut "valide" sont utilisables.
            if "ban" in ref:
                if ref.get("ban_status") == "valide":
                    ref_lat = ref["ban"].get("lat")
                    ref_lon = ref["ban"].get("lon")
                else:
                    ref_lat = ref_lon = None

            # Compléter uniquement une géolocalisation manquante
            if ev.lat is None and in_bbox(ref_lat, ref_lon):
                ev.lat, ev.lon = ref_lat, ref_lon
                ev.flags.append("geoloc_depuis_referentiel")

    return {
        "events": kept,
        "rejected": rejected,
        "stats": {
            "entree": len(raw_events),
            "sortie": len(kept),
            "rejets": len(rejected),
            "lieux_rapproches": matched,
            "sans_geoloc": sum(1 for e in kept if e.lat is None)
        }
    }


def load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]



def to_postgres(events: list[CleanEvent], dsn: str) -> None:
    """Charge les événements de manière idempotente dans PostgreSQL."""
    import psycopg

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for ev in events:
            # Par défaut, aucun lieu n'est associé à l'événement.
            venue_id = None

            # On crée ou met à jour un lieu uniquement s'il est connu.
            if ev.venue_name and ev.venue_norm:
                source = (
                    "referentiel"
                    if "geoloc_depuis_referentiel" in ev.flags
                    else "openagenda"
                )

                cur.execute(
                    """
                    INSERT INTO venues (name, name_norm, city, lat, lon, source)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name_norm, city) DO UPDATE
                    SET lat = COALESCE(venues.lat, EXCLUDED.lat),
                        lon = COALESCE(venues.lon, EXCLUDED.lon)
                    RETURNING venue_id
                    """,
                    (
                        ev.venue_name,
                        ev.venue_norm,
                        ev.city,
                        ev.lat,
                        ev.lon,
                        source
                    )
                )
                venue_id = cur.fetchone()[0]

            # Insertion ou mise à jour de l'événement.
            cur.execute(
                """
                INSERT INTO events (
                    event_uid, title, description, keywords,
                    venue_id, status, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_uid) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    keywords = EXCLUDED.keywords,
                    venue_id = EXCLUDED.venue_id,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    loaded_at = now()
                """,
                (
                    ev.uid,
                    ev.title,
                    ev.description,
                    ev.keywords,
                    venue_id,
                    ev.status,
                    ev.updated_at
                )
            )

            # Remplacement des occurrences de cet événement.
            cur.execute(
                "DELETE FROM event_occurrences WHERE event_uid = %s",
                (ev.uid,)
            )

            cur.executemany(
                """
                INSERT INTO event_occurrences (event_uid, begin_ts, end_ts)
                VALUES (%s, %s, %s)
                """,
                [(ev.uid, begin, end) for begin, end in ev.occurrences]
            )



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
