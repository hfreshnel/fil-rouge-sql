from __future__ import annotations

from collections import Counter
from typing import Any

from transform.clean_events import BBOX


def check_quality(
    events: list,
    rejected: list[dict],
    max_rejection_rate: float = 0.20
) -> dict[str, Any]:
    """
    Contrôle la qualité des événements avant leur chargement.

    Retourne un rapport contenant :
    - les indicateurs qualité ;
    - les anomalies détectées ;
    - le statut global du contrôle.
    """

    errors = []
    warnings = []

    total = len(events) + len(rejected)
    rejection_rate = len(rejected) / total if total else 0.0

    # 1. Vérifier l'identifiant et le titre
    for event in events:
        if not event.uid:
            errors.append({
                "uid": event.uid,
                "reason": "identifiant_manquant"
            })

        if not event.title or not event.title.strip():
            errors.append({
                "uid": event.uid,
                "reason": "titre_manquant"
            })

    # 2. Vérifier l'unicité des identifiants
    uid_counts = Counter(event.uid for event in events)

    for uid, count in uid_counts.items():
        if count > 1:
            errors.append({
                "uid": uid,
                "reason": "identifiant_duplique",
                "count": count
            })

    # 3. Vérifier les occurrences
    for event in events:
        if not event.occurrences:
            errors.append({
                "uid": event.uid,
                "reason": "aucune_occurrence"
            })
            continue

        for begin, end in event.occurrences:
            if begin is None or end is None or end < begin:
                errors.append({
                    "uid": event.uid,
                    "reason": "date_incoherente"
                })

    # 4. Vérifier les coordonnées géographiques
    lat_min, lat_max = BBOX["lat"]
    lon_min, lon_max = BBOX["lon"]

    for event in events:
        lat, lon = event.lat, event.lon

        if lat is None and lon is None:
            warnings.append({
                "uid": event.uid,
                "reason": "geolocalisation_absente"
            })
            continue

        if lat is None or lon is None:
            errors.append({
                "uid": event.uid,
                "reason": "coordonnees_incompletes"
            })
            continue

        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            errors.append({
                "uid": event.uid,
                "reason": "coordonnees_hors_zone"
            })

    # 5. Vérifier le taux de rejet
    if rejection_rate > max_rejection_rate:
        errors.append({
            "reason": "taux_rejet_trop_eleve",
            "actual": round(rejection_rate, 4),
            "maximum": max_rejection_rate
        })

    return {
        "passed": len(errors) == 0,
        "metrics": {
            "total": total,
            "valid": len(events),
            "rejected": len(rejected),
            "rejection_rate": round(rejection_rate, 4),
            "warnings": len(warnings),
            "errors": len(errors)
        },
        "errors": errors,
        "warnings": warnings
    }
