"""À lancer par l'INTERVENANTE avant le module, avec une bonne connexion : photographie les vraies sources
dans secours/reel/ pour pouvoir travailler hors connexion si une API tombe pendant les cours.

    export OA_KEY=...                       # clé OpenAgenda
    python secours/preparer_secours.py --gbfs-url <URL gbfs.json Lovélo>   # tout (~ 30 à 60 min selon la connexion)
    python secours/preparer_secours.py --seulement openagenda comptages    # une partie seulement

Puis copier secours/reel/ sur une clé USB et sur un drive partagé (environ 2 Go avec Electronics).
Le serveur secours/serveur_api_local.py sert automatiquement secours/reel/ s'il existe.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ICI = Path(__file__).parent
OUT = ICI / "reel"
PORTAIL = "https://data.metropole-rouen-normandie.fr/api/explore/v2.1/catalog/datasets"
OA = "https://api.openagenda.com/v2"


def http_json(url: str, params=None, headers=None, essais: int = 5):
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    for k in range(essais):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:                      # 429, 5xx, coupure : on attend et on réessaie
            print(f"  erreur {e} — nouvel essai dans {2 ** k} s")
            time.sleep(2 ** k)
    raise RuntimeError(f"échec : {url}")


def openagenda(slug: str, debut: str, fin: str):
    key = os.environ["OA_KEY"]
    h = {"key": key}
    uid = http_json(f"{OA}/agendas", [("slug[]", slug)], h)["agendas"][0]["uid"]
    y, m = map(int, debut.split("-")); ye, me = map(int, fin.split("-"))
    vus, n = set(), 0
    with open(OUT / "evenements_bruts.jsonl", "w", encoding="utf-8") as f:
        while (y, m) <= (ye, me):
            ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
            after = []
            while True:
                p = [("size", "100"), ("detailed", "1"), ("timings[gte]", f"{date(y, m, 1)}T00:00:00.000Z"),
                     ("timings[lte]", f"{date(ny, nm, 1)}T00:00:00.000Z")] + [("after[]", str(a)) for a in after]
                d = http_json(f"{OA}/agendas/{uid}/events", p, h)
                for ev in d.get("events") or []:
                    cle = (ev.get("uid"), ev.get("updatedAt"))
                    if cle not in vus:              # on garde les doublons « métier » : ils sont à nettoyer en cours
                        vus.add(cle); f.write(json.dumps(ev, ensure_ascii=False) + "\n"); n += 1
                after = d.get("after") or []
                if not d.get("events") or not after:
                    break
            print(f"  {y}-{m:02d} : {n} événements cumulés")
            y, m = ny, nm


def portail(jeu: str, nom_fichier: str):
    url = f"{PORTAIL}/{jeu}/exports/csv?delimiter=%3B"
    print("  téléchargement", url)
    urllib.request.urlretrieve(url, OUT / nom_fichier)


def lovelo(gbfs_url: str, releves: int, pas: int):
    g = http_json(gbfs_url)
    data = g["data"]; lang = data.get("fr") or data.get("en") or next(iter(data.values()))
    feeds = {f["name"]: f["url"] for f in lang["feeds"]}
    info = http_json(feeds["station_information"])["data"]["stations"]
    json.dump([{k: s.get(k) for k in ("station_id", "name", "lat", "lon", "capacity")} for s in info],
              open(OUT / "lovelo_stations.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(OUT / "lovelo_status.jsonl", "w", encoding="utf-8") as f:
        for i in range(releves):
            f.write(json.dumps(http_json(feeds["station_status"]), ensure_ascii=False) + "\n")
            if i < releves - 1:
                time.sleep(pas)


def amazon(category: str, kinds, n: int | None):
    from datasets import load_dataset
    for kind in kinds:
        ds = load_dataset("McAuley-Lab/Amazon-Reviews-2023", f"raw_{kind}_{category}", split="full", streaming=True)
        if n:
            ds = ds.take(n)
        nom = OUT / f"amazon_{category}_{'reviews' if kind == 'review' else 'meta'}.jsonl"
        k = 0
        with open(nom, "w", encoding="utf-8") as f:
            for row in ds:
                row.pop("images", None); row.pop("videos", None)
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n"); k += 1
        print(f"  {nom.name} : {k:,} lignes")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seulement", nargs="*", default=["openagenda", "comptages", "lieux", "lovelo", "amazon"])
    p.add_argument("--slug", default="rouen-normandie-metropole")
    p.add_argument("--debut", default="2024-01"); p.add_argument("--fin", default="2026-11")
    p.add_argument("--jeu-lieux", help="identifiant du jeu « équipements culturels » sur le portail (optionnel)")
    p.add_argument("--gbfs-url", help="URL gbfs.json Lovélo (transport.data.gouv.fr)")
    p.add_argument("--releves-lovelo", type=int, default=30); p.add_argument("--pas-lovelo", type=int, default=60)
    p.add_argument("--n-electronics", type=int, default=1_000_000)
    a = p.parse_args()
    OUT.mkdir(exist_ok=True)
    if "openagenda" in a.seulement:
        print("OpenAgenda"); openagenda(a.slug, a.debut, a.fin)
    if "comptages" in a.seulement:
        print("Comptages vélo"); portail("eco-counter-data", "eco-counter-data.csv")
    if "lieux" in a.seulement and a.jeu_lieux:
        print("Référentiel des lieux"); portail(a.jeu_lieux, "referentiel_lieux_brut.csv")
    if "lovelo" in a.seulement and a.gbfs_url:
        print("Lovélo"); lovelo(a.gbfs_url, a.releves_lovelo, a.pas_lovelo)
    if "amazon" in a.seulement:
        print("Amazon Reviews"); amazon("All_Beauty", ["review", "meta"], None); amazon("Electronics", ["review"], a.n_electronics)
    json.dump({"nature": "RÉEL (photographie des sources)", "date": date.today().isoformat()},
              open(OUT / "LISEZMOI.json", "w", encoding="utf-8"), ensure_ascii=False)
    print("terminé :", OUT)
