"""API locale de secours : imite les API utilisées en cours, à partir des données de secours.

Démarrage (aucune dépendance en dehors de Python) :
    python secours/serveur_api_local.py                  # http://localhost:8765
    python secours/serveur_api_local.py --taux-429 0.1 --taux-503 0.05 --latence-ms 150   # pannes simulées

Puis, dans le terminal où l'on lance les scripts du kit :
    export OA_API=http://localhost:8765/openagenda/v2            # collecteur OpenAgenda (fil rouge)
    export PORTAIL_API=http://localhost:8765/ods/api/explore/v2.1/catalog/datasets   # comptages vélo
    export HF_ROWS_API=http://localhost:8765/hf/rows              # TP3 (Dataset Viewer HuggingFace)
    # Lovélo : python collecte/lovelo_collector.py --gbfs-url http://localhost:8765/gbfs/gbfs.json
    (Windows PowerShell : $env:OA_API="http://localhost:8765/openagenda/v2")

Routes imitées :
  /openagenda/v2/agendas?slug[]=...                          -> {"agendas": [{"uid", "slug"}]}
  /openagenda/v2/agendas/<uid>/events?size&timings[gte]&timings[lte]&after[]   -> {"total", "events", "after"}
  /ods/api/explore/v2.1/catalog/datasets/<jeu>/exports/csv|parquet   (parquet : nécessite pyarrow)
  /gbfs/gbfs.json, /gbfs/station_information.json, /gbfs/station_status.json
  /hf/rows?dataset&config&split&offset&length               -> {"rows": [{"row_idx", "row"}], "num_rows_total"}

Les données viennent de secours/reel/ si ce dossier existe (préparé avec preparer_secours.py), sinon de
secours/synthetique/ (généré avec generer_synthetique.py). L'option --donnees force le choix.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ICI = Path(__file__).parent
CFG = {}
DATA = {}


def charger(dossier: Path) -> None:
    ev_path = dossier / "evenements_bruts.jsonl"
    events = [json.loads(l) for l in open(ev_path, encoding="utf-8") if l.strip()] if ev_path.exists() else []

    def debut(ev):
        try:
            return min(t["begin"] for t in ev.get("timings") or [])
        except ValueError:
            return ""
    for ev in events:
        ev["_debut"] = debut(ev)
    events.sort(key=lambda e: (e["_debut"], e.get("uid") or 0))
    DATA["events"] = events
    DATA["dossier"] = dossier
    st = dossier / "lovelo_stations.json"
    DATA["stations"] = json.load(open(st, encoding="utf-8")) if st.exists() else []
    hf = sorted(dossier.glob("amazon_*_reviews.jsonl"))
    DATA["hf_rows"] = [json.loads(l) for l in open(hf[0], encoding="utf-8")] if hf else None


def iso_utc(s: str) -> str:
    """Compare les dates en UTC quel que soit le fuseau d'écriture."""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return s


def faux_avis(i: int) -> dict:
    """Avis fictif déterministe (si aucun extrait Amazon réel n'a été préparé)."""
    h = int(hashlib.md5(str(i).encode()).hexdigest(), 16)
    return {"rating": float(1 + h % 5), "title": f"Avis {i}", "text": f"Texte d'avis fictif numéro {i}. " * (1 + h % 4),
            "asin": f"B{h % 10**9:09d}", "parent_asin": f"B{h % 10**7:09d}", "user_id": f"U{h % 10**6:06d}",
            "timestamp": 1_600_000_000_000 + (h % 10**11), "helpful_vote": h % 7, "verified_purchase": bool(h % 3)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if CFG.get("verbeux"):
            super().log_message(fmt, *args)

    def envoyer(self, code: int, corps, ctype="application/json", entetes=None):
        data = corps if isinstance(corps, bytes) else json.dumps(corps, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if CFG["latence"]:
            time.sleep(CFG["latence"] / 1000 * random.uniform(0.5, 1.5))
        r = random.random()
        if r < CFG["taux_429"]:
            return self.envoyer(429, {"error": "Too Many Requests (simulé)"}, entetes={"Retry-After": "1"})
        if r < CFG["taux_429"] + CFG["taux_503"]:
            return self.envoyer(503, {"error": "Service Unavailable (simulé)"})
        p = u.path.rstrip("/").split("/")[1:]
        try:
            if p[:3] == ["openagenda", "v2", "agendas"]:
                return self.openagenda(p[3:], q)
            if p[:1] == ["ods"] and "exports" in p:
                return self.ods(p, q)
            if p[:1] == ["gbfs"]:
                return self.gbfs(p[1] if len(p) > 1 else "gbfs.json")
            if p == ["hf", "rows"]:
                return self.hf(q)
        except Exception as e:      # erreur côté serveur : 500, comme une vraie API
            return self.envoyer(500, {"error": str(e)})
        self.envoyer(404, {"error": f"route inconnue : {u.path}"})

    # --- OpenAgenda ------------------------------------------------------
    def openagenda(self, reste, q):
        if not reste:
            slug = (q.get("slug[]") or ["rouen-normandie-metropole"])[0]
            return self.envoyer(200, {"agendas": [{"uid": 4242, "slug": slug, "title": "Agenda (secours local)"}]})
        if len(reste) == 2 and reste[1] == "events":
            size = min(int((q.get("size") or ["20"])[0]), 300)
            gte, lte = (q.get("timings[gte]") or [None])[0], (q.get("timings[lte]") or [None])[0]
            evs = DATA["events"]
            if gte or lte:
                g, l = iso_utc(gte) if gte else "", iso_utc(lte) if lte else "9999"
                evs = [e for e in evs if any(g <= iso_utc(t["begin"]) < l for t in e.get("timings") or [])]
            total = len(evs)
            after = q.get("after[]")
            if after:
                cle = (after[0], int(after[1]) if len(after) > 1 else 0)
                evs = [e for e in evs if (e["_debut"], e.get("uid") or 0) > cle]
            page = evs[:size]
            suite = [page[-1]["_debut"], page[-1].get("uid") or 0] if len(evs) > size else None
            sortie = [{k: v for k, v in e.items() if not k.startswith("_")} for e in page]
            return self.envoyer(200, {"total": total, "events": sortie, "after": suite})
        self.envoyer(404, {"error": "route OpenAgenda inconnue"})

    # --- Portail open data (export) --------------------------------------
    def ods(self, p, q):
        jeu, fmt = p[p.index("datasets") + 1], p[-1]
        csv = DATA["dossier"] / f"{jeu}.csv"
        parquet = DATA["dossier"] / f"{jeu}.parquet"
        if fmt == "parquet":
            if parquet.exists():
                return self.envoyer(200, parquet.read_bytes(), "application/octet-stream")
            import pandas as pd             # conversion à la volée (pyarrow requis côté étudiant)
            buf = io.BytesIO(); pd.read_csv(csv, sep=";").to_parquet(buf, index=False)
            return self.envoyer(200, buf.getvalue(), "application/octet-stream")
        if fmt == "csv" and csv.exists():
            return self.envoyer(200, csv.read_bytes(), "text/csv; charset=utf-8")
        self.envoyer(404, {"error": f"jeu {jeu} absent du dossier de secours"})

    # --- GBFS Lovélo -------------------------------------------------------
    def gbfs(self, fichier):
        base = f"http://{self.headers.get('Host')}/gbfs"
        now = int(time.time())
        if fichier == "gbfs.json":
            feeds = [{"name": n, "url": f"{base}/{n}.json"} for n in ("station_information", "station_status")]
            return self.envoyer(200, {"last_updated": now, "ttl": 60, "data": {"fr": {"feeds": feeds}}})
        if fichier == "station_information.json":
            return self.envoyer(200, {"last_updated": now, "data": {"stations": DATA["stations"]}})
        if fichier == "station_status.json":
            st = []
            for s in DATA["stations"]:
                velos = random.randint(0, s["capacity"])
                st.append({"station_id": s["station_id"], "num_bikes_available": velos,
                           "num_docks_available": s["capacity"] - velos, "is_renting": random.random() > 0.03,
                           "last_reported": now - random.randint(0, 120)})
            return self.envoyer(200, {"last_updated": now, "data": {"stations": st}})
        self.envoyer(404, {"error": "flux GBFS inconnu"})

    # --- Dataset Viewer HuggingFace -----------------------------------------
    def hf(self, q):
        off, length = int((q.get("offset") or ["0"])[0]), min(int((q.get("length") or ["100"])[0]), 100)
        rows = DATA["hf_rows"]
        total = len(rows) if rows is not None else 700_000
        idx = range(off, min(off + length, total))
        data = [{"row_idx": i, "row": rows[i] if rows is not None else faux_avis(i), "truncated_cells": []} for i in idx]
        self.envoyer(200, {"rows": data, "num_rows_total": total, "num_rows_per_page": 100, "partial": False})


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--port", type=int, default=8765)
    a.add_argument("--donnees", choices=["auto", "reel", "synthetique"], default="auto")
    a.add_argument("--taux-429", type=float, default=0.0, help="part des requêtes refusées en 429 (ex. 0.1)")
    a.add_argument("--taux-503", type=float, default=0.0, help="part des requêtes en erreur 503")
    a.add_argument("--latence-ms", type=int, default=0, help="latence moyenne ajoutée à chaque réponse")
    a.add_argument("--verbeux", action="store_true")
    o = a.parse_args()
    dossier = ICI / ("reel" if (o.donnees == "reel" or (o.donnees == "auto" and (ICI / "reel").exists())) else "synthetique")
    if not (dossier / "evenements_bruts.jsonl").exists():
        raise SystemExit(f"{dossier} vide : lancer generer_synthetique.py (ou preparer_secours.py avec réseau)")
    charger(dossier)
    CFG.update(taux_429=o.taux_429, taux_503=o.taux_503, latence=o.latence_ms, verbeux=o.verbeux)
    print(f"API locale de secours sur http://localhost:{o.port}  (données : {dossier.name}, {len(DATA['events'])} événements)")
    ThreadingHTTPServer(("0.0.0.0", o.port), Handler).serve_forever()
