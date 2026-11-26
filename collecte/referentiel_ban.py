
"""Construction et validation du référentiel des lieux avec la BAN."""

import json
import time
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

import requests

API_URL = "https://data.geopf.fr/geocodage/search"
INPUT_FILE = Path("evenements_bruts.jsonl")
OUTPUT_FILE = Path("data/referentiel_ban.json")
DELAY = 0.15

# Périmètre géographique du projet
LAT_MIN, LAT_MAX = 49.20, 49.60
LON_MIN, LON_MAX = 0.70, 1.35


def distance_m(lat1, lon1, lat2, lon2):
    """Calcule la distance entre deux coordonnées en mètres."""
    lat1, lon1, lat2, lon2 = map(
        radians, [lat1, lon1, lat2, lon2]
    )

    h = (
        sin((lat2 - lat1) / 2) ** 2
        + cos(lat1) * cos(lat2)
        * sin((lon2 - lon1) / 2) ** 2
    )

    return 6371000 * 2 * atan2(sqrt(h), sqrt(1 - h))


def geocode(address):
    """Recherche une adresse dans la BAN avec gestion des erreurs temporaires."""
    for attempt in range(3):
        try:
            response = requests.get(
                API_URL,
                params={"q": address, "limit": 1},
                timeout=30,
            )

            if response.status_code in (502, 503, 504):
                if attempt < 2:
                    wait = 2 ** (attempt + 1)
                    print(f"BAN indisponible. Nouvelle tentative dans {wait}s...")
                    time.sleep(wait)
                    continue

            response.raise_for_status()

            features = response.json().get("features", [])
            if not features:
                return None

            feature = features[0]
            properties = feature["properties"]
            lon, lat = feature["geometry"]["coordinates"]

            return {
                "ban_id": properties.get("banId"),
                "label": properties.get("label"),
                "score": properties.get("score"),
                "lon": lon,
                "lat": lat,
            }

        except requests.RequestException as error:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue

            print(f"Erreur BAN pour '{address}' : {error}")

        except (ValueError, KeyError, IndexError) as error:
            print(f"Réponse BAN invalide pour '{address}' : {error}")
            return None

    return None



def validate_result(location, ban):
    """Valide une correspondance selon le score, la zone et la distance."""
    if not ban:
        return "non_valide", None

    try:
        lat_ban = float(ban["lat"])
        lon_ban = float(ban["lon"])
        score = float(ban["score"])

        lat_oa = float(location["latitude"])
        lon_oa = float(location["longitude"])
    except (TypeError, ValueError, KeyError):
        return "non_valide", None

    dans_zone = (
        LAT_MIN <= lat_ban <= LAT_MAX
        and LON_MIN <= lon_ban <= LON_MAX
    )

    if not dans_zone or score < 0.70:
        return "non_valide", None

    distance = distance_m(lat_oa, lon_oa, lat_ban, lon_ban)

    if score >= 0.90 and distance <= 100:
        return "valide", round(distance, 1)

    if distance <= 500:
        return "a_verifier", round(distance, 1)

    return "non_valide", round(distance, 1)


def main():
    lieux = {}

    with INPUT_FILE.open(encoding="utf-8") as file:
        for line in file:
            event = json.loads(line)
            location = event.get("location")

            if not isinstance(location, dict):
                continue

            uid = location.get("uid")
            if uid is not None:
                lieux[uid] = location

    referentiel = []
    total = len(lieux)

    for index, location in enumerate(lieux.values(), start=1):
        address = (location.get("address") or "").strip()
        ban = geocode(address) if address else None

        status, distance = validate_result(location, ban)

        referentiel.append({
            "openagenda_uid": location.get("uid"),
            "name": location.get("name"),
            "city": location.get("city") or location.get("adminLevel4"),
            "address_original": address,
            "openagenda_lat": location.get("latitude"),
            "openagenda_lon": location.get("longitude"),
            "ban": ban,
            "distance_m": distance,
            "ban_status": status,
        })

        if index % 50 == 0 or index == total:
            print(f"Progression : {index}/{total}")

        time.sleep(DELAY)

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(referentiel, file, ensure_ascii=False, indent=2)

    print("\nRéférentiel BAN terminé.")
    print("Lieux traités :", total)
    print("Correspondances fiables :", sum(x["ban_status"] == "valide" for x in referentiel))
    print("À vérifier :", sum(x["ban_status"] == "a_verifier" for x in referentiel))
    print("Non validées :", sum(x["ban_status"] == "non_valide" for x in referentiel))
    print("Fichier :", OUTPUT_FILE)


if __name__ == "__main__":
    main()
