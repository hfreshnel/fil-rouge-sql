"""Fil rouge — Chargement des comptages vélo horaires de la Métropole dans PostgreSQL (fourni, séance 2).

Source : jeu « eco-counter-data » du portail data.metropole-rouen-normandie.fr, exporté via l'API Explore v2.1.

Secours hors connexion : --file secours/synthetique/eco-counter-data.csv (ou secours/reel/...)

Étape 1 — PROFILER (séance 1) : afficher les colonnes réelles, types, valeurs manquantes
    python load_comptages.py --profile
Étape 2 — CHARGER en indiquant les colonnes source si la détection automatique se trompe
    python load_comptages.py --col-counter <col> --col-name <col> --col-ts <col> --col-count <col> --col-lat <col> --col-lon <col>

Le chargement est IDEMPOTENT : ON CONFLICT DO UPDATE sur (counter_id, ts).
"""
from __future__ import annotations

import argparse
import io
import os
import urllib.request

import pandas as pd

PORTAIL = os.getenv("PORTAIL_API", "https://data.metropole-rouen-normandie.fr/api/explore/v2.1/catalog/datasets")   # secours : API locale
DSN = os.getenv("PG_DSN", "postgresql://etl:etl@localhost:5432/metropole")

# Mots-clés pour deviner les colonnes (à corriger après le profilage si besoin)
GUESS = {
    "counter": ["id_compteur", "counter_id", "id_site", "channel", "compteur_id", "id"],
    "name": ["nom_compteur", "name", "nom_site", "nom", "libelle"],
    "ts": ["date_heure", "date", "datetime", "horodatage", "heure", "timestamp"],
    "count": ["comptage", "nb_passages", "count", "counts", "valeur", "value", "passages"],
    "lat": ["latitude", "lat"],
    "lon": ["longitude", "lon", "lng"],
}


def download(dataset: str, fmt: str = "parquet") -> pd.DataFrame:
    url = f"{PORTAIL}/{dataset}/exports/{fmt}"
    print("téléchargement :", url)
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    return pd.read_parquet(io.BytesIO(data)) if fmt == "parquet" else pd.read_csv(io.BytesIO(data), sep=";")


def guess(df: pd.DataFrame, key: str) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for cand in GUESS[key]:
        if cand in cols:
            return cols[cand]
    for cand in GUESS[key]:
        for low, orig in cols.items():
            if cand in low:
                return orig
    return None


def profile(df: pd.DataFrame) -> None:
    print(f"{len(df):,} lignes, {df.shape[1]} colonnes\n")
    prof = pd.DataFrame({"type": df.dtypes.astype(str), "nulls_%": (df.isna().mean() * 100).round(1),
                         "distincts": df.nunique(), "exemple": df.iloc[0] if len(df) else None})
    print(prof.to_string())
    print("\ndétection automatique :", {k: guess(df, k) for k in GUESS})


def load(df: pd.DataFrame, cols: dict) -> None:
    import psycopg
    missing = [k for k in ("counter", "ts", "count") if not cols.get(k)]
    if missing:
        raise SystemExit(f"colonnes non identifiées : {missing} -> utiliser --col-*")
    d = pd.DataFrame({
        "counter_id": df[cols["counter"]].astype(str),
        "name": df[cols["name"]] if cols.get("name") else None,
        "ts": pd.to_datetime(df[cols["ts"]], utc=True, errors="coerce").dt.floor("h"),
        "passages": pd.to_numeric(df[cols["count"]], errors="coerce"),
        "lat": pd.to_numeric(df[cols["lat"]], errors="coerce") if cols.get("lat") else None,
        "lon": pd.to_numeric(df[cols["lon"]], errors="coerce") if cols.get("lon") else None,
    })
    bad = d["ts"].isna() | d["passages"].isna() | (d["passages"] < 0)
    print(f"lignes rejetées (date ou comptage invalide) : {int(bad.sum()):,}")
    d = d[~bad]
    # plusieurs lignes pour la même heure (ex. un sens par ligne) -> somme
    hourly = d.groupby(["counter_id", "ts"], as_index=False)["passages"].sum()
    counters = d.groupby("counter_id", as_index=False).agg(name=("name", "first"), lat=("lat", "first"),
                                                           lon=("lon", "first"))
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO counters VALUES (%s, %s, %s, %s)
               ON CONFLICT (counter_id) DO UPDATE SET name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon""",
            counters.astype(object).where(counters.notna(), None).itertuples(index=False, name=None))
        cur.execute("CREATE TEMP TABLE stage (LIKE counts_hourly) ON COMMIT DROP")
        with cur.copy("COPY stage (counter_id, ts, passages) FROM STDIN") as cp:
            for row in hourly.itertuples(index=False, name=None):
                cp.write_row((row[0], row[1].to_pydatetime(), int(row[2])))
        cur.execute("""INSERT INTO counts_hourly SELECT * FROM stage
                       ON CONFLICT (counter_id, ts) DO UPDATE SET passages = EXCLUDED.passages""")
        cur.execute("ANALYZE counts_hourly")
        conn.commit()
    print(f"{len(counters)} compteurs, {len(hourly):,} heures chargées")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="eco-counter-data")
    p.add_argument("--profile", action="store_true")
    p.add_argument("--file", help="fichier local (CSV ; ou Parquet) au lieu du téléchargement, ex. secours/synthetique/eco-counter-data.csv")
    for k in GUESS:
        p.add_argument(f"--col-{k}")
    a = p.parse_args()
    if a.file:
        df = pd.read_parquet(a.file) if a.file.endswith(".parquet") else pd.read_csv(a.file, sep=";")
    else:
        df = download(a.dataset)
    if a.profile:
        profile(df)
    else:
        load(df, {k: getattr(a, f"col_{k}") or guess(df, k) for k in GUESS})
