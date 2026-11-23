"""Jeu de secours SYNTHÉTIQUE du fil rouge (dernier recours, hors connexion).

À utiliser seulement si les API sont indisponibles ET que le jeu réel préparé par l'intervenante
(dossier secours/reel/, voir preparer_secours.py) n'est pas disponible.

Les données sont FICTIVES mais ont la même forme que les vraies sources, avec les mêmes défauts à nettoyer :
  - OpenAgenda : HTML dans les descriptions, champs multilingues, doublons (même uid mis à jour, uid différents
    pour le même événement), dates incohérentes, géolocalisation absente ou hors Métropole, annulations ;
  - comptages vélo : heures manquantes, pannes (longues séries de 0), surfréquentation autour des événements ;
  - Lovélo : stations et relevés de disponibilité.

    python generer_synthetique.py            # écrit dans secours/synthetique/ (graine fixe : résultat reproductible)
"""
from __future__ import annotations

import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

UTC = timezone.utc
PARIS = timezone(timedelta(hours=1))   # simplification : décalage d'hiver toute l'année (données fictives)

# Lieux fictifs inspirés de la Métropole (coordonnées approximatives)
LIEUX = [
    ("Le 106 – Salle des Musiques Actuelles", "Rouen", 49.4365, 1.0786),
    ("Théâtre des Arts", "Rouen", 49.4412, 1.0866),
    ("Kindarena", "Rouen", 49.4479, 1.0634),
    ("Zénith de Rouen", "Le Grand-Quevilly", 49.3994, 1.0482),
    ("Musée des Beaux-Arts", "Rouen", 49.4446, 1.0938),
    ("Panorama XXL", "Rouen", 49.4441, 1.0749),
    ("Hangar 23", "Rouen", 49.4385, 1.1018),
    ("Chapelle Corneille", "Rouen", 49.4453, 1.0960),
    ("Parc des Expositions", "Rouen", 49.3995, 1.0603),
    ("Jardin des Plantes", "Rouen", 49.4247, 1.0798),
    ("Quais bas rive gauche", "Rouen", 49.4369, 1.0890),
    ("Théâtre Charles Dullin", "Le Grand-Quevilly", 49.4093, 1.0384),
    ("Espace Culturel François Mitterrand", "Canteleu", 49.4410, 1.0213),
    ("Le Rive Gauche", "Saint-Étienne-du-Rouvray", 49.3786, 1.1047),
    ("Halle aux Toiles", "Rouen", 49.4418, 1.0917),
]
# Variantes d'écriture rencontrées dans les saisies (rapprochement de lieux à faire)
VARIANTES = {
    "Le 106 – Salle des Musiques Actuelles": ["Le 106", "le 106 - SMAC", "Le106"],
    "Théâtre des Arts": ["Theatre des Arts", "Opéra de Rouen - Théâtre des Arts"],
    "Kindarena": ["KINDARENA", "Palais des sports Kindarena"],
}
TYPES = [("Concert", ["concert", "musique"], 3), ("Spectacle", ["spectacle", "théâtre"], 2),
         ("Exposition", ["exposition", "art"], 0), ("Match", ["sport"], 2), ("Marché", ["marché", "gastronomie"], 1),
         ("Conférence", ["conférence"], 1), ("Festival", ["festival", "musique"], 4), ("Visite guidée", ["visite", "patrimoine"], 1)]
# Compteurs vélo fictifs
COMPTEURS = [
    ("CPT-001", "Pont Boieldieu", 49.4372, 1.0869), ("CPT-002", "Quai de Paris", 49.4392, 1.0965),
    ("CPT-003", "Avenue de Bretagne", 49.4268, 1.0798), ("CPT-004", "Pont Guillaume-le-Conquérant", 49.4348, 1.0738),
    ("CPT-005", "Boulevard de l'Yser", 49.4470, 1.0985), ("CPT-006", "Quai Gaston Boulet", 49.4430, 1.0640),
    ("CPT-007", "Rue Jeanne d'Arc", 49.4440, 1.0880), ("CPT-008", "Avenue Jean Rondeaux", 49.4318, 1.0700),
    ("CPT-009", "Boulevard d'Orléans", 49.4250, 1.0905), ("CPT-010", "Route de Lyons-la-Forêt", 49.4560, 1.1220),
    ("CPT-011", "Quai du Havre", 49.4402, 1.0750), ("CPT-012", "Avenue des Canadiens", 49.4120, 1.0560),
]


def html_desc(rng, titre):
    morceaux = [f"<p>{titre} : un rendez-vous <b>à ne pas manquer</b>&nbsp;!</p>",
                f"<p>Venez découvrir {titre.lower()}.<br/>Entrée libre</p>",
                f"{titre} — infos &amp; réservations sur place.", None]
    return morceaux[rng.integers(len(morceaux))]


def multilingue(rng, fr):
    if fr is None:
        return None
    r = rng.random()
    return {"fr": fr} if r < 0.7 else ({"fr": fr, "en": fr} if r < 0.9 else {"en": fr})


def gen_events(rng, start, end, n):
    events, uid = [], 900000
    jours = (end - start).days
    for _ in range(n):
        uid += int(rng.integers(1, 7))
        typ, kw, poids = TYPES[rng.integers(len(TYPES))]
        nom, ville, lat, lon = LIEUX[rng.integers(len(LIEUX))]
        nom_saisi = rng.choice(VARIANTES.get(nom, [nom]) + [nom])
        titre = f"{typ} {['du printemps', 'de la Seine', 'en famille', 'nocturne', 'au centre', 'des quais', 'découverte'][rng.integers(7)]}"
        d0 = start + timedelta(days=int(rng.integers(jours)))
        h = int(rng.choice([10, 14, 18, 19, 20, 20, 21]))
        nb = 1 if typ != "Exposition" else int(rng.integers(5, 30))
        timings = []
        for k in range(nb):
            b = datetime(d0.year, d0.month, d0.day, h, 0, tzinfo=PARIS) + timedelta(days=k)
            e = b + timedelta(hours=int(rng.integers(1, 4)) if typ != "Exposition" else 8)
            timings.append({"begin": b.isoformat(), "end": e.isoformat()})
        loc = {"name": nom_saisi, "city": ville, "latitude": round(lat + rng.normal(0, 0.0004), 6),
               "longitude": round(lon + rng.normal(0, 0.0004), 6)}
        r = rng.random()
        if r < 0.05:
            loc["latitude"] = loc["longitude"] = None                      # géoloc absente
        elif r < 0.07:
            loc["latitude"], loc["longitude"] = 48.8566, 2.3522             # géoloc hors Métropole (Paris)
        ev = {"uid": uid, "title": multilingue(rng, titre), "description": multilingue(rng, html_desc(rng, titre)),
              "keywords": {"fr": [k.capitalize() if rng.random() < 0.3 else k for k in kw] + ([kw[0] + " "] if rng.random() < 0.2 else [])},
              "timings": timings, "location": loc,
              "status": int(rng.choice([1, 1, 1, 1, 1, 1, 1, 1, 2, 5, 6])),   # 1 programmé, 2 reporté, 5 complet, 6 annulé
              "updatedAt": (datetime.combine(d0, datetime.min.time(), UTC) - timedelta(days=int(rng.integers(1, 60)))).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
              "_poids": poids, "_lat": lat, "_lon": lon}
        r = rng.random()
        if r < 0.02:
            ev["timings"] = [{"begin": timings[0]["end"], "end": timings[0]["begin"]}]   # dates incohérentes
        elif r < 0.03:
            ev["timings"] = []                                                          # aucune date
        elif r < 0.035:
            ev["title"] = {"fr": "  <br/> "}                                            # titre vide
        events.append(ev)
    # doublons : même uid mis à jour plus tard, et même événement saisi sous deux uid
    for ev in list(rng.choice(events, size=n // 40, replace=False)):
        maj = dict(ev); maj["updatedAt"] = "2026-11-01T09:00:00.000Z"; maj["status"] = 6 if rng.random() < 0.3 else ev["status"]
        events.append(maj)
    for ev in list(rng.choice(events, size=n // 50, replace=False)):
        copie = dict(ev); uid += 3; copie["uid"] = uid
        events.append(copie)
    rng.shuffle(events)
    return events


def gen_counts(rng, events, start, end):
    heures = pd.date_range(start, end, freq="h", tz=UTC, inclusive="left")
    hod = heures.hour.values; dow = heures.dayofweek.values
    # profil horaire : pointes 8h et 17-18h en semaine, après-midi le week-end
    semaine = np.array([1, .5, .3, .3, .5, 2, 6, 14, 22, 12, 8, 9, 11, 10, 9, 10, 14, 22, 20, 12, 8, 5, 3, 2], float)
    weekend = np.array([2, 1, .5, .4, .4, .6, 1, 2, 4, 7, 10, 12, 13, 14, 15, 15, 14, 12, 10, 8, 6, 4, 3, 2], float)
    base_h = np.where(dow < 5, semaine[hod], weekend[hod])
    jour_an = heures.dayofyear.values
    saison = 1 + 0.35 * np.sin(2 * math.pi * (jour_an - 100) / 365)     # plus de vélo l'été
    occ = []   # (lat, lon, début UTC, fin UTC, intensité)
    for ev in events:
        if ev.get("status") == 6 or not ev["timings"]:
            continue
        for t in ev["timings"][:3]:
            b = pd.Timestamp(t["begin"]).tz_convert(UTC); e = pd.Timestamp(t["end"]).tz_convert(UTC)
            if e > b:
                occ.append((ev["_lat"], ev["_lon"], b - pd.Timedelta(hours=1), e + pd.Timedelta(hours=1), ev["_poids"]))
    frames = []
    for cid, nom, lat, lon, in COMPTEURS:
        niveau = rng.uniform(8, 40)
        lam = niveau * base_h * saison / 10
        for (elat, elon, b, e, poids) in occ:
            dist = math.hypot((elat - lat) * 111_000, (elon - lon) * 73_000)
            if dist < 900 and poids:
                m = (heures >= b) & (heures < e)
                lam[m] *= 1 + 0.15 * poids * (1 - dist / 900) * 3
        n = rng.poisson(lam)
        df = pd.DataFrame({"id_compteur": cid, "nom_compteur": nom, "date": heures, "comptage": n.astype(float),
                           "latitude": lat, "longitude": lon})
        # pannes : séries de 0 de 1 à 6 jours
        for _ in range(int(rng.integers(0, 4))):
            i = int(rng.integers(len(df) - 200)); df.loc[i:i + int(rng.integers(24, 144)), "comptage"] = 0
        # heures manquantes (lignes absentes) et quelques valeurs invalides
        df = df.drop(index=rng.choice(len(df), size=len(df) // 200, replace=False))
        bad = rng.choice(df.index, size=5, replace=False); df.loc[bad[:3], "comptage"] = -1; df.loc[bad[3:], "comptage"] = np.nan
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = out["date"].dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")    # l'export du portail donne des chaînes
    return out


def gen_lovelo(rng):
    stations = []
    for i, (nom, ville, lat, lon) in enumerate(LIEUX[:12]):
        stations.append({"station_id": f"LV{i + 1:03d}", "name": f"Station {nom.split('–')[0].strip()}",
                         "lat": round(lat + 0.0015, 6), "lon": round(lon - 0.0012, 6), "capacity": int(rng.choice([15, 20, 25, 30]))})
    return stations


def main(out: Path, start: str, end: str, n_events: int, seed: int):
    rng = np.random.default_rng(seed)
    random.seed(seed)
    out.mkdir(parents=True, exist_ok=True)
    s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
    events = gen_events(rng, s.date(), e.date(), n_events)
    counts = gen_counts(rng, events, s, e)
    with open(out / "evenements_bruts.jsonl", "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps({k: v for k, v in ev.items() if not k.startswith("_")}, ensure_ascii=False) + "\n")
    ref = [{"name": n, "city": c, "lat": la, "lon": lo} for n, c, la, lo in LIEUX]
    json.dump(ref, open(out / "referentiel_lieux.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    counts.to_csv(out / "eco-counter-data.csv", sep=";", index=False)   # même format que l'export CSV du portail
    stations = gen_lovelo(rng)
    json.dump(stations, open(out / "lovelo_stations.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    meta = {"nature": "SYNTHÉTIQUE (données fictives, même forme que les sources réelles)", "graine": seed,
            "periode": [start, end], "evenements_bruts": len(events), "lignes_comptages": len(counts),
            "compteurs": len(COMPTEURS), "stations_lovelo": len(stations)}
    json.dump(meta, open(out / "LISEZMOI.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(Path(__file__).parent / "synthetique"))
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--end", default="2026-11-01")
    p.add_argument("--events", type=int, default=3000)
    p.add_argument("--seed", type=int, default=2026)
    a = p.parse_args()
    main(Path(a.out), a.start, a.end, a.events, a.seed)
