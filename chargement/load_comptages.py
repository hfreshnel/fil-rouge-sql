"""Fil rouge — Chargement des comptages vélo horaires de la Métropole dans PostgreSQL.

Source : jeu « eco-counter-data » du portail data.metropole-rouen-normandie.fr, exporté via l'API Explore v2.1.
Secours hors connexion : --file secours/synthetique/eco-counter-data.csv (ou secours/reel/...)

Corrections appliquées d'après la fiche d'anomalies (docs/profilage.md) :
  - coordonnées : décodées depuis `location` (point WKB) quand il n'y a pas de colonnes lat/lon ;
  - `status` : deux formats mélangés (texte et liste JSON) ramenés à 3 valeurs : brut, corrige, valide ;
  - lignes marquées « deleted » à la source : rejetées (quarantaine) ;
  - plusieurs lignes pour le même (compteur, heure) : on en garde UNE, la plus fiable. On n'additionne pas :
    ce ne sont pas deux sens de circulation, mais deux versions de la même mesure ;
  - colonnes inutiles (travel_mode, annee, date_j, photourl, commune) : ignorées.

Les lignes rejetées sont écrites dans data/quarantaine/comptages_rejetes.csv avec leur raison.

Commandes :
    python chargement/load_comptages.py --profile                       # colonnes, types, détection automatique
    python chargement/load_comptages.py                                 # téléchargement depuis le portail
    python chargement/load_comptages.py --file data/brut/eco-counter-data.parquet   # copie locale (profilage)

Le chargement est IDEMPOTENT : ON CONFLICT DO UPDATE sur (counter_id, ts), on peut le relancer sans doublon.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import struct
import urllib.request
from pathlib import Path

import pandas as pd

PORTAIL = os.getenv("PORTAIL_API", "https://data.metropole-rouen-normandie.fr/api/explore/v2.1/catalog/datasets")   # secours : API locale
DSN = os.getenv("PG_DSN", "postgresql://etl:etl@localhost:5432/metropole")
RACINE = Path(__file__).resolve().parent.parent
QUARANTAINE = RACINE / "data" / "quarantaine" / "comptages_rejetes.csv"   # data/ est ignoré par git

# Mots-clés pour deviner les colonnes (à forcer avec --col-* si la détection se trompe)
GUESS = {
    "counter": ["id_compteur", "counter_id", "id_site", "channel", "compteur_id", "id"],
    "name": ["nom_compteur", "name", "nom_site", "nom", "libelle"],
    "ts": ["date_heure", "date", "datetime", "horodatage", "heure", "timestamp"],
    "count": ["comptage", "nb_passages", "count", "counts", "valeur", "value", "passages"],
    "lat": ["latitude", "lat"],
    "lon": ["longitude", "lon", "lng"],
    "location": ["location", "geo_point_2d", "coordonnees"],   # jeu réel : point WKB, pas de lat/lon séparées
    "status": ["status", "statut"],
}

# Ordre de préférence quand deux lignes décrivent la même heure : la donnée validée d'abord.
PRIORITE_STATUT = {"valide": 0, "corrige": 1, "brut": 2}


# ---------- décodage des valeurs ----------
def point_wkb(b) -> tuple[float, float] | None:
    """Décode un point au format WKB (ou EWKB avec SRID) -> (lat, lon). C'est le format de `location` dans le Parquet.

    Structure d'un point WKB : 1 octet d'ordre des octets, 4 octets de type (1 = Point),
    [4 octets de SRID si EWKB], puis deux flottants de 8 octets : x (longitude) et y (latitude).
    """
    if not isinstance(b, (bytes, bytearray)) or len(b) < 21:
        return None
    ordre = "<" if b[0] == 1 else ">"                # 1er octet : 1 = little endian, 0 = big endian
    type_geom = struct.unpack(ordre + "I", b[1:5])[0]
    debut = 9 if type_geom & 0x20000000 else 5       # EWKB : 4 octets de SRID après le type
    if type_geom & 0xFFFF != 1 or len(b) < debut + 16:  # 1 = Point
        return None
    x, y = struct.unpack(ordre + "dd", b[debut:debut + 16])
    return y, x                                      # WKB stocke (x = longitude, y = latitude)


def coordonnees(valeur) -> tuple[float, float] | None:
    """Accepte les formes rencontrées : WKB (Parquet), « lat, lon » (CSV du portail), {lat, lon}."""
    if isinstance(valeur, (bytes, bytearray)):
        return point_wkb(valeur)
    if isinstance(valeur, dict):
        lat, lon = valeur.get("lat"), valeur.get("lon")
        return (float(lat), float(lon)) if lat is not None and lon is not None else None
    if isinstance(valeur, str) and "," in valeur:
        try:
            lat, lon = (float(x) for x in valeur.split(",")[:2])
            return lat, lon
        except ValueError:
            return None
    return None


def statut_normalise(valeur) -> str | None:
    """Ramène `status` à brut / corrige / valide, ou « supprime » pour une ligne marquée deleted.

    Formats vus au profilage : « Donnée brut », « Donnée corrigée », et des listes JSON comme
    ["validated"], ["deleted", "validated"], ["modified", "deleted"]. None si la valeur est absente ou inconnue.
    """
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    texte = str(valeur).strip()
    if texte.startswith("["):                        # format liste JSON
        try:
            marques = {str(m).lower() for m in json.loads(texte)}
        except json.JSONDecodeError:
            return None
        if "deleted" in marques:                     # « supprimée » l'emporte sur les autres marques
            return "supprime"
        if "validated" in marques:
            return "valide"
        if "modified" in marques:
            return "corrige"
        return None
    texte = texte.lower()                            # format texte
    if "corrig" in texte:
        return "corrige"
    if "brut" in texte:
        return "brut"
    if "valid" in texte:
        return "valide"
    return None


# ---------- lecture ----------
def download(dataset: str, fmt: str = "parquet") -> pd.DataFrame:
    url = f"{PORTAIL}/{dataset}/exports/{fmt}"
    print("téléchargement :", url)
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    return pd.read_parquet(io.BytesIO(data)) if fmt == "parquet" else pd.read_csv(io.BytesIO(data), sep=";")


def guess(df: pd.DataFrame, key: str) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for cand in GUESS[key]:                          # 1) nom exact
        if cand in cols:
            return cols[cand]
    for cand in GUESS[key]:                          # 2) nom qui contient le mot-clé
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


# ---------- préparation (sans base : c'est cette partie que testent les tests) ----------
def preparer(df: pd.DataFrame, cols: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Applique les règles de la fiche d'anomalies.

    Renvoie (heures à charger, compteurs, lignes rejetées avec leur raison).
    """
    missing = [k for k in ("counter", "ts", "count") if not cols.get(k)]
    if missing:
        raise SystemExit(f"colonnes non identifiées : {missing} -> utiliser --col-*")

    statut_source = df[cols["status"]] if cols.get("status") else pd.Series(None, index=df.index, dtype="object")
    d = pd.DataFrame({
        "counter_id": df[cols["counter"]].astype(str),
        "name": df[cols["name"]] if cols.get("name") else None,
        "ts": pd.to_datetime(df[cols["ts"]], utc=True, errors="coerce").dt.floor("h"),
        "passages": pd.to_numeric(df[cols["count"]], errors="coerce"),
        "status_source": statut_source,
        "status": statut_source.map(statut_normalise),
    })

    # Signalement : statut présent dans la source mais inconnu -> ligne gardée, status à NULL
    inconnus = d["status_source"].notna() & d["status"].isna()
    if inconnus.any():
        print(f"⚠ statuts inconnus (gardés, status NULL) : {d.loc[inconnus, 'status_source'].value_counts().to_dict()}")

    # Rejets : on note la PREMIÈRE raison rencontrée, dans cet ordre
    raison = pd.Series(None, index=d.index, dtype="object")

    def rejeter(masque: pd.Series, texte: str) -> None:
        raison[masque & raison.isna()] = texte

    rejeter(d["status"] == "supprime", "supprimée à la source")
    rejeter(d["ts"].isna(), "date illisible")
    rejeter(d["passages"].isna(), "comptage vide ou non numérique")
    rejeter(d["passages"] < 0, "comptage négatif")
    rejeter(d["passages"] % 1 != 0, "comptage non entier")

    # Doublons (même compteur, même heure) parmi les lignes restantes : on garde la plus fiable.
    # Tri stable par priorité de statut, puis duplicated(keep="first") marque les autres versions.
    gardees = d[raison.isna()]
    priorite = gardees["status"].map(PRIORITE_STATUT).fillna(len(PRIORITE_STATUT))
    ordre = gardees.assign(_p=priorite).sort_values("_p", kind="stable")
    doublons = ordre.duplicated(["counter_id", "ts"], keep="first")
    rejeter(d.index.isin(ordre.index[doublons]), "doublon (compteur, heure) : version moins fiable écartée")

    rejets = d[raison.notna()].assign(raison=raison[raison.notna()]).drop(columns="status")
    heures = d.loc[raison.isna(), ["counter_id", "ts", "passages", "status"]].copy()
    heures["passages"] = heures["passages"].astype(int)
    heures = heures.sort_values(["counter_id", "ts"], ignore_index=True)

    # Compteurs : nom et coordonnées de la première ligne de chaque compteur (constants d'après le profilage)
    premiers = d.drop_duplicates("counter_id").index
    compteurs = d.loc[premiers, ["counter_id", "name"]].reset_index(drop=True)
    if cols.get("lat") and cols.get("lon"):          # jeu synthétique : colonnes latitude / longitude
        compteurs["lat"] = pd.to_numeric(df.loc[premiers, cols["lat"]], errors="coerce").to_numpy()
        compteurs["lon"] = pd.to_numeric(df.loc[premiers, cols["lon"]], errors="coerce").to_numpy()
    elif cols.get("location"):                       # jeu réel : point WKB dans `location`
        points = [coordonnees(v) for v in df.loc[premiers, cols["location"]]]
        compteurs["lat"] = [p[0] if p else None for p in points]
        compteurs["lon"] = [p[1] if p else None for p in points]
    else:
        compteurs["lat"] = compteurs["lon"] = None
    sans_coord = int(compteurs["lat"].isna().sum())
    if sans_coord:
        print(f"⚠ compteurs sans coordonnées : {sans_coord} (ils ne seront rattachés à aucun lieu)")

    return heures, compteurs, rejets


def ecrire_quarantaine(rejets: pd.DataFrame, chemin: Path = QUARANTAINE) -> None:
    """Écrase le fichier à chaque exécution : il reflète toujours le dernier chargement."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    rejets.to_csv(chemin, index=False)
    print(f"lignes rejetées : {len(rejets):,} -> {chemin.relative_to(RACINE)}")
    for texte, n in rejets["raison"].value_counts().items():
        print(f"  {texte} : {n:,}")


# ---------- chargement en base ----------
def load(df: pd.DataFrame, cols: dict) -> None:
    import psycopg
    heures, compteurs, rejets = preparer(df, cols)
    ecrire_quarantaine(rejets)
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO counters VALUES (%s, %s, %s, %s)
               ON CONFLICT (counter_id) DO UPDATE SET name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon""",
            compteurs.astype(object).where(compteurs.notna(), None).itertuples(index=False, name=None))
        # Table de transit + COPY (rapide sur ~1 M lignes), puis upsert vers la vraie table
        cur.execute("CREATE TEMP TABLE stage (LIKE counts_hourly) ON COMMIT DROP")
        with cur.copy("COPY stage (counter_id, ts, passages, status) FROM STDIN") as cp:
            for cid, ts, passages, statut in heures.itertuples(index=False, name=None):
                cp.write_row((cid, ts.to_pydatetime(), int(passages), None if pd.isna(statut) else statut))
        cur.execute("""INSERT INTO counts_hourly (counter_id, ts, passages, status)
                       SELECT counter_id, ts, passages, status FROM stage
                       ON CONFLICT (counter_id, ts) DO UPDATE
                       SET passages = EXCLUDED.passages, status = EXCLUDED.status""")
        cur.execute("ANALYZE counts_hourly")
        # Le calendrier matérialisé (optimisation Q3, sql/fr_02) est une copie : il faut le recalculer
        # après chaque chargement, sinon Q2, Q4 et l'indice liraient les anciens comptages.
        # to_regclass renvoie NULL si la vue n'existe pas encore (fr_02 pas encore exécuté).
        cur.execute("SELECT to_regclass('mv_calendrier') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("REFRESH MATERIALIZED VIEW mv_calendrier")
            cur.execute("ANALYZE mv_calendrier")
            print("vue matérialisée mv_calendrier rafraîchie")
        conn.commit()
    print(f"{len(compteurs)} compteurs, {len(heures):,} heures chargées")


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
