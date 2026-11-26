"""Fil rouge — Profilage des sources (séance 1) : chiffre les anomalies à reporter dans docs/profilage.md.

Le script ne modifie rien : il lit les sources et affiche, pour chacune, les volumes et les anomalies trouvées.
À vous ensuite de choisir une règle par anomalie (rejet, correction ou signalement).

    python chargement/profilage.py                           # les trois sources
    python chargement/profilage.py comptages                 # portail Métropole (copie locale dans data/brut/)
    python chargement/profilage.py comptages --comptages secours/synthetique/eco-counter-data.csv
    python chargement/profilage.py evenements --evenements secours/reel/evenements_bruts.jsonl
    python chargement/profilage.py lieux                     # + lieux de l'agenda absents du référentiel

Par défaut, événements et lieux viennent de secours/reel/ si le dossier existe, sinon de secours/synthetique/.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

try:                                    # python -m chargement.profilage
    from chargement.load_comptages import PORTAIL, coordonnees, guess
except ImportError:                     # python chargement/profilage.py
    from load_comptages import PORTAIL, coordonnees, guess

RACINE = Path(__file__).resolve().parent.parent
SECOURS = RACINE / "secours" / ("reel" if (RACINE / "secours" / "reel").exists() else "synthetique")
CACHE = RACINE / "data" / "brut"                     # data/ est ignoré par git
BBOX = {"lat": (49.20, 49.60), "lon": (0.70, 1.35)}  # emprise de la Métropole, la même que transform/clean_events.py
UNE_HEURE = pd.Timedelta(hours=1)
# Codes de statut OpenAgenda (d'après la doc développeur OpenAgenda : à vérifier et à citer dans profilage.md)
STATUTS_OA = {1: "programmé", 2: "reprogrammé", 3: "déplacé en ligne", 4: "reporté", 5: "complet", 6: "annulé"}
TAG_RE = re.compile(r"<[^>]+>")
ENTITE_RE = re.compile(r"&[#a-zA-Z0-9]+;")


# ---------- affichage ----------
def titre(texte: str) -> None:
    print(f"\n=== {texte} " + "=" * max(0, 72 - len(texte)))


def ligne(libelle: str, n: int, total: int | None = None, exemple=None) -> None:
    """Une anomalie = un libellé, un volume (et sa part du total), un exemple."""
    part = f" ({n / total:.3%})" if total else ""
    ex = f"   ex. {exemple}" if exemple is not None else ""
    print(f"  {libelle:<52} {n:>10,}{part}{ex}")


# ---------- utilitaires ----------
def sans_html(texte: str) -> str:
    return " ".join(html.unescape(TAG_RE.sub(" ", texte)).split())


def normaliser(texte) -> str:
    """Minuscules, sans accents ni ponctuation : sert uniquement à repérer les doublons et les variantes."""
    if not texte:
        return ""
    t = unicodedata.normalize("NFKD", str(texte).lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def dans_metropole(lat, lon) -> bool:
    return (lat is not None and lon is not None and not pd.isna(lat) and not pd.isna(lon)
            and BBOX["lat"][0] <= lat <= BBOX["lat"][1] and BBOX["lon"][0] <= lon <= BBOX["lon"][1])


def texte_fr(valeur) -> tuple[str, list[str]]:
    """Champ multilingue OpenAgenda -> (texte français ou à défaut une autre langue, langues présentes)."""
    if isinstance(valeur, dict):
        langues = [k for k, v in valeur.items() if v]
        return str(valeur.get("fr") or next((valeur[k] for k in langues), "")), langues
    return (str(valeur), ["?"]) if valeur else ("", [])


def date_iso(valeur) -> datetime | None:
    try:
        return datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------- comptages vélo ----------
def lire_comptages(fichier: str | None, jeu: str, rafraichir: bool) -> tuple[pd.DataFrame, str]:
    if fichier:
        df = pd.read_parquet(fichier) if fichier.endswith(".parquet") else pd.read_csv(fichier, sep=";")
        return df, fichier
    cible = CACHE / f"{jeu}.parquet"
    if rafraichir or not cible.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        url = f"{PORTAIL}/{jeu}/exports/parquet"
        print("téléchargement :", url)
        tmp = cible.with_suffix(".part")             # pas de fichier à moitié écrit si le téléchargement coupe
        with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as f:
            f.write(r.read())
        tmp.replace(cible)
    return pd.read_parquet(cible), f"{cible.relative_to(RACINE)} (copie du portail, --rafraichir pour la mettre à jour)"


def profiler_comptages(df: pd.DataFrame, source: str) -> None:
    titre(f"COMPTAGES VÉLO — {source}")
    n = len(df)
    col = {k: guess(df, k) for k in ("counter", "name", "ts", "count", "lat", "lon")}
    print(f"  {n:,} lignes, {df.shape[1]} colonnes : {list(df.columns)}")
    print(f"  colonnes reconnues : {col}")
    if not all(col[k] for k in ("counter", "ts", "count")):
        sys.exit("compteur, date ou comptage non reconnu : adapter GUESS dans load_comptages.py")

    cid = df[col["counter"]].astype(str)
    brut_ts = df[col["ts"]]
    if pd.api.types.is_datetime64_any_dtype(brut_ts):
        ts = brut_ts.dt.tz_convert("UTC") if brut_ts.dt.tz is not None else brut_ts.dt.tz_localize("UTC")
    else:
        ts = pd.to_datetime(brut_ts, utc=True, errors="coerce", format="ISO8601")
    v = pd.to_numeric(df[col["count"]], errors="coerce")
    noms = df.groupby(cid)[col["name"]].first() if col["name"] else pd.Series(dtype=str)
    print(f"  {cid.nunique()} compteurs, du {ts.min()} au {ts.max()}")

    titre("Valeurs manquantes (compte exact, sans arrondi)")
    rien = True
    for c in df.columns:
        vides = int(df[c].isna().sum())
        if pd.api.types.is_string_dtype(df[c]):
            vides += int(df[c].fillna("x").astype(str).str.strip().eq("").sum())
        if vides:
            ligne(f"{c} vide", vides, n)
            rien = False
    if rien:
        print("  aucune")

    titre("Colonnes sans information")
    constantes = [c for c in df.columns if df[c].nunique(dropna=False) == 1]
    for c in constantes:
        ligne(f"{c} : une seule valeur pour toutes les lignes", n, n, repr(df[c].iloc[0]))
    if not constantes and "date_j" not in df.columns:
        print("  aucune")
    if "date_j" in df.columns:
        jour = pd.to_datetime(df["date_j"].astype(str), errors="coerce")
        local = ts.dt.tz_convert("Europe/Paris").dt.tz_localize(None).dt.normalize()
        utc = ts.dt.tz_localize(None).dt.normalize()
        ligne("date_j ≠ jour de `date` en heure de Paris", int((jour != local).sum()), n)
        ligne("date_j ≠ jour de `date` en UTC", int((jour != utc).sum()), n)
    if "annee" in df.columns:
        print(f"  annee : valeurs {sorted(map(str, df['annee'].dropna().unique()))}")

    statut = next((c for c in df.columns if c.lower() in ("status", "statut")), None)
    if statut:
        titre(f"Valeurs de la colonne `{statut}`")
        for valeur, k in df[statut].value_counts(dropna=False).items():
            ligne(repr(valeur), int(k), n)

    titre("Comptages")
    ligne("comptage vide ou non numérique", int(v.isna().sum()), n)
    ligne("comptage négatif", int((v < 0).sum()), n, v[v < 0].unique()[:5].tolist() or None)
    ligne("comptage non entier", int(((v % 1) != 0).sum() - v.isna().sum()), n)
    ligne("comptage à 0", int((v == 0).sum()), n)
    print(f"  répartition : {v.describe(percentiles=[.5, .99, .999]).round(1).to_dict()}")

    titre("Dates")
    ligne("date illisible", int(ts.isna().sum()), n, brut_ts[ts.isna()].iloc[0] if ts.isna().any() else None)
    pas_pile = ts.notna() & (ts != ts.dt.floor("h"))
    ligne("date qui ne tombe pas pile sur l'heure", int(pas_pile.sum()), n, ts[pas_pile].iloc[0] if pas_pile.any() else None)

    titre("Informations du compteur qui changent d'une ligne à l'autre")
    seuil_temporel = 10 * cid.nunique()              # au-delà : colonne qui varie avec le temps (dates, comptages)
    rien = True
    for c in df.columns:
        if (c in (col["counter"], col["ts"], col["count"], statut) or df[c].nunique() > seuil_temporel
                or c.lower().startswith(("date", "annee", "year"))):   # colonnes de temps : varient normalement
            continue
        par_compteur = df.groupby(cid)[c].nunique()
        if (par_compteur > 1).any():
            ex = par_compteur[par_compteur > 1].index[0]
            ligne(f"{c} : plusieurs valeurs pour un même compteur", int((par_compteur > 1).sum()), None,
                  f"compteur {ex} -> {par_compteur[ex]} valeurs")
            rien = False
    if rien:
        print("  aucune")

    titre("Coordonnées des compteurs")
    premiere = df.loc[~cid.duplicated()]
    if col["lat"] and col["lon"]:
        pts = list(zip(pd.to_numeric(premiere[col["lat"]], errors="coerce"),
                       pd.to_numeric(premiere[col["lon"]], errors="coerce")))
        print(f"  colonnes {col['lat']} / {col['lon']}")
    else:
        geo = next((c for c in df.columns if c.lower() in ("location", "geo_point_2d", "geolocalisation", "coordonnees")), None)
        if not geo:
            print("  aucune colonne de coordonnées trouvée")
            pts = [None] * len(premiere)
        else:
            print(f"  pas de colonnes lat/lon : coordonnées dans `{geo}` ({type(premiere[geo].iloc[0]).__name__}),"
                  f" ex. {premiere[geo].iloc[0]!r:.60} -> {coordonnees(premiere[geo].iloc[0])}")
            pts = [coordonnees(x) for x in premiere[geo]]
    pts = [p if p and not pd.isna(p[0]) else None for p in pts]
    ligne("compteurs sans coordonnées lisibles", sum(p is None for p in pts), len(pts))
    hors = [(i, p) for i, p in zip(cid[premiere.index], pts) if p and not dans_metropole(*p)]
    ligne("compteurs hors de la Métropole", len(hors), len(pts), hors[0] if hors else None)

    # Une ligne par (compteur, heure) pour la suite ; les doublons sont mesurés juste avant
    cle = pd.DataFrame({"cid": cid, "ts": ts, "v": v}).dropna(subset=["ts"])
    titre("Doublons (même compteur, même heure)")
    en_double = cle.duplicated(["cid", "ts"], keep=False)
    ligne("lignes identiques sur toutes les colonnes", int(df.duplicated().sum()), n)
    ligne("heures (compteur, heure) présentes plusieurs fois", int(cle[en_double].groupby(["cid", "ts"]).ngroups))
    ligne("  lignes en trop", int(cle.duplicated(["cid", "ts"]).sum()), n)
    ligne("  dont avec le même comptage", int(cle.duplicated(["cid", "ts", "v"]).sum()), n)
    if en_double.any():
        if statut:
            print(f"  `{statut}` des lignes en double : {df.loc[cle.index[en_double], statut].value_counts().to_dict()}")
        exemple = cle[en_double].sort_values(["cid", "ts"]).iloc[0]
        print("  exemple :")
        print(df.loc[(cid == exemple.cid) & (ts == exemple.ts)].drop(columns=[c for c in df.columns if df[c].dtype == object
                                                                              and isinstance(df[c].iloc[0], bytes)])
              .to_string(max_colwidth=40))
        print("  ⚠ load_comptages.py ADDITIONNE les lignes d'une même heure : un vrai doublon y compte double.")

    u = cle.drop_duplicates(["cid", "ts"]).sort_values(["cid", "ts"]).reset_index(drop=True)

    titre("Heures manquantes (entre la 1re et la dernière mesure de chaque compteur)")
    g = u.groupby("cid").agg(premiere=("ts", "min"), derniere=("ts", "max"), presentes=("ts", "size"),
                             plus_long_trou=("ts", lambda s: s.diff().max()))
    g["attendues"] = ((g["derniere"] - g["premiere"]) / UNE_HEURE).astype(int) + 1
    g["manquantes"] = g["attendues"] - g["presentes"]
    g["part_%"] = (100 * g["manquantes"] / g["attendues"]).round(1)
    g.insert(0, "nom", noms.reindex(g.index).str.slice(0, 32))
    ligne("heures manquantes, tous compteurs", int(g["manquantes"].sum()), int(g["attendues"].sum()))
    print(g.sort_values("manquantes", ascending=False)
          .assign(premiere=lambda d: d.premiere.dt.date, derniere=lambda d: d.derniere.dt.date)
          .drop(columns="presentes").to_string())

    titre("Pannes probables : au moins 24 heures consécutives à 0 (cf. Q4)")
    zero = u["v"].eq(0)
    rupture = (zero != zero.shift()) | (u["cid"] != u["cid"].shift()) | (u["ts"].diff() != UNE_HEURE)
    serie = rupture.cumsum()
    series = (u[zero].groupby(serie[zero])
              .agg(cid=("cid", "first"), debut=("ts", "min"), fin=("ts", "max"), heures=("ts", "size")))
    pannes = series[series["heures"] >= 24]
    ligne("séries de 24 h ou plus à 0", len(pannes))
    ligne("  heures concernées", int(pannes["heures"].sum()), len(u))
    ligne("  compteurs concernés", int(pannes["cid"].nunique()), int(u["cid"].nunique()))
    if len(pannes):
        print("  les plus longues :")
        print(pannes.nlargest(5, "heures").assign(nom=lambda d: d.cid.map(noms).str.slice(0, 32))
              .to_string(index=False))

    titre("Pics suspects : comptage > 5 × le 99e centile du compteur")
    p99 = u[u["v"] > 0].groupby("cid")["v"].quantile(0.99)
    pics = u[u["v"] > 5 * u["cid"].map(p99)]
    ligne("heures concernées", len(pics), len(u))
    if len(pics):
        print(pics.nlargest(5, "v").assign(p99=lambda d: d.cid.map(p99)).to_string(index=False))


# ---------- événements OpenAgenda ----------
def lire_evenements(chemin: Path) -> tuple[list[dict], int]:
    evenements, illisibles = [], 0
    with open(chemin, encoding="utf-8") as f:
        for texte in f:
            if texte.strip():
                try:
                    evenements.append(json.loads(texte))
                except json.JSONDecodeError:
                    illisibles += 1
    return evenements, illisibles


def profiler_evenements(evs: list[dict], illisibles: int, chemin: Path) -> None:
    titre(f"ÉVÉNEMENTS OPENAGENDA — {chemin.relative_to(RACINE) if chemin.is_relative_to(RACINE) else chemin}")
    if "synthetique" in str(chemin):
        print("  ⚠ jeu SYNTHÉTIQUE : données fictives, à indiquer dans profilage.md")
    n = len(evs)
    print(f"  {n:,} événements (lignes)")
    ligne("ligne JSON illisible", illisibles)

    c = Counter()                   # compteurs d'anomalies
    ex = {}                         # un exemple par anomalie

    def note(cle: str, exemple=None) -> None:
        c[cle] += 1
        ex.setdefault(cle, exemple)

    langues, statuts, nb_occ = Counter(), Counter(), Counter()
    debuts = []
    for e in evs:
        uid = e.get("uid")
        if uid in (None, ""):
            note("uid absent")
        titre_txt, l_titre = texte_fr(e.get("title"))
        langues.update(l_titre)
        if not isinstance(e.get("title"), dict) or not e["title"].get("fr"):
            note("titre sans version française", e.get("title"))
        if not sans_html(titre_txt):
            note("titre vide (une fois le HTML retiré)", e.get("title"))
        elif TAG_RE.search(titre_txt):
            note("titre contenant du HTML", titre_txt[:60])
        desc, _ = texte_fr(e.get("description"))
        if not desc:
            note("description absente")
        if TAG_RE.search(desc):
            note("description contenant des balises HTML", desc[:60])
        if ENTITE_RE.search(desc):
            note("description contenant des entités HTML (&amp; …)", ENTITE_RE.search(desc).group())
        mots = (e.get("keywords") or {}).get("fr") or [] if isinstance(e.get("keywords"), dict) else e.get("keywords") or []
        if len({normaliser(m) for m in mots}) < len(mots):
            note("mots-clés en double (casse, espaces)", mots)
        if not e.get("updatedAt"):
            note("updatedAt absent")
        statuts[e.get("status")] += 1

        occ = e.get("timings") or []
        nb_occ[min(len(occ), 10)] += 1
        if not occ:
            note("aucune date (timings vide)", uid)
        incoherentes = 0
        for t in occ:
            d, f = date_iso(t.get("begin")), date_iso(t.get("end"))
            if d is None or f is None:
                note("occurrence avec une date illisible ou absente", t)
                continue
            debuts.append(d)
            if f < d:
                incoherentes += 1
            elif f == d:
                note("occurrence de durée nulle (fin = début)", t)
        if incoherentes:
            note("événement avec au moins une occurrence fin < début", occ[0])
            if incoherentes == len(occ):
                note("  dont toutes ses occurrences fin < début", uid)

        lieu = e.get("location") or {}
        if not lieu:
            note("lieu absent", uid)
        else:
            if not lieu.get("name"):
                note("lieu sans nom", uid)
            if not lieu.get("city"):
                note("lieu sans ville", lieu.get("name"))
            lat, lon = lieu.get("latitude"), lieu.get("longitude")
            if lat is None or lon is None:
                note("lieu sans coordonnées", lieu.get("name"))
            elif not dans_metropole(lat, lon):
                note("coordonnées hors de la Métropole", (lieu.get("name"), lat, lon))

    for cle, k in sorted(c.items(), key=lambda x: -x[1]):
        ligne(cle, k, n, ex[cle] if ex[cle] is not None else None)

    titre("Langues des titres, statuts, nombre d'occurrences")
    print(f"  langues : {dict(langues.most_common())}")
    for code, k in sorted(statuts.items(), key=lambda x: str(x[0])):
        ligne(f"statut {code} ({STATUTS_OA.get(code, 'inconnu')})", k, n)
    print(f"  occurrences par événement (10 = 10 et plus) : {dict(sorted(nb_occ.items()))}")
    if debuts:
        print(f"  dates de début : du {min(debuts)} au {max(debuts)}")

    titre("Doublons")
    par_uid = Counter(e.get("uid") for e in evs if e.get("uid") not in (None, ""))
    multi = {u: k for u, k in par_uid.items() if k > 1}
    ligne("uid présents plusieurs fois", len(multi), None, next(iter(multi), None))
    ligne("  lignes en trop", sum(multi.values()) - len(multi), n)
    meme_maj = Counter((e.get("uid"), e.get("updatedAt")) for e in evs if e.get("uid") in multi)
    ligne("  dont même uid ET même updatedAt (copie exacte)", sum(k - 1 for k in meme_maj.values()), n)

    # Doublon « métier » : même événement saisi sous deux uid (même titre, même lieu, même 1re date)
    groupes: dict[tuple, set] = {}
    for e in evs:
        occ = [date_iso(t.get("begin")) for t in e.get("timings") or []]
        occ = [d for d in occ if d]
        if e.get("uid") in (None, "") or not occ:
            continue
        cle = (normaliser(texte_fr(e.get("title"))[0]), normaliser((e.get("location") or {}).get("name")), min(occ))
        groupes.setdefault(cle, set()).add(e.get("uid"))
    metier = {k: u for k, u in groupes.items() if len(u) > 1}
    ligne("même titre + même lieu + même 1re date, uid différents", len(metier), None,
          next(((k[0], sorted(u)) for k, u in metier.items()), None))

    titre("Lieux saisis dans l'agenda")
    noms_bruts = Counter((e.get("location") or {}).get("name") for e in evs if (e.get("location") or {}).get("name"))
    noms_norm = {normaliser(x) for x in noms_bruts}
    print(f"  {len(noms_bruts)} noms différents tels que saisis, {len(noms_norm)} après normalisation "
          "(minuscules, sans accents ni ponctuation)")
    print("  les plus fréquents (repérer les variantes d'un même lieu) :")
    for nom, k in sorted(noms_bruts.items(), key=lambda x: (normaliser(x[0]), -x[1]))[:40]:
        print(f"    {k:>6}  {nom}")


# ---------- référentiel des lieux ----------
def lire_lieux(chemin: Path) -> pd.DataFrame:
    if chemin.suffix == ".json":
        donnees = json.load(open(chemin, encoding="utf-8"))
        df = pd.DataFrame(donnees.get("results", donnees) if isinstance(donnees, dict) else donnees)
    else:
        df = pd.read_csv(chemin, sep=";")
    cols = {c.lower(): c for c in df.columns}
    choix = lambda *cands: next((cols[x] for x in cands if x in cols), None)
    out = pd.DataFrame({"name": df[choix("name", "nom", "libelle", "nom_equipement")],
                        "city": df[choix("city", "commune", "ville")] if choix("city", "commune", "ville") else None})
    if choix("lat", "latitude") and choix("lon", "longitude"):
        out["lat"] = pd.to_numeric(df[choix("lat", "latitude")], errors="coerce")
        out["lon"] = pd.to_numeric(df[choix("lon", "longitude")], errors="coerce")
    else:
        pts = df[choix("geo_point_2d", "location", "coordonnees")].map(coordonnees)
        out["lat"] = pts.map(lambda p: p[0] if p else None)
        out["lon"] = pts.map(lambda p: p[1] if p else None)
    return out


def profiler_lieux(ref: pd.DataFrame, chemin: Path, evs: list[dict] | None) -> None:
    titre(f"RÉFÉRENTIEL DES LIEUX — {chemin.relative_to(RACINE) if chemin.is_relative_to(RACINE) else chemin}")
    n = len(ref)
    print(f"  {n} lieux")
    ligne("lieu sans nom", int(ref["name"].isna().sum()), n)
    ligne("lieu sans ville", int(ref["city"].isna().sum()), n)
    ligne("lieu sans coordonnées", int((ref["lat"].isna() | ref["lon"].isna()).sum()), n)
    hors = ref[ref["lat"].notna() & ~ref.apply(lambda r: dans_metropole(r["lat"], r["lon"]), axis=1)]
    ligne("coordonnées hors de la Métropole", len(hors), n, hors["name"].iloc[0] if len(hors) else None)
    cle = ref["name"].map(normaliser) + " | " + ref["city"].map(normaliser)
    ligne("doublons (même nom normalisé, même ville)", int(cle.duplicated().sum()), n)

    if evs:
        titre("Rapprochement exact agenda -> référentiel (nom normalisé + ville)")
        connus = set(cle)
        lieux_agenda = Counter()
        for e in evs:
            lieu = e.get("location") or {}
            if lieu.get("name"):
                lieux_agenda[(lieu["name"], lieu.get("city"))] += 1
        absents = {k: v for k, v in lieux_agenda.items()
                   if f"{normaliser(k[0])} | {normaliser(k[1])}" not in connus}
        ligne("lieux de l'agenda (nom + ville distincts)", len(lieux_agenda))
        ligne("  sans correspondance exacte dans le référentiel", len(absents), len(lieux_agenda))
        ligne("  événements concernés", sum(absents.values()), sum(lieux_agenda.values()))
        print("  les plus fréquents sans correspondance (variantes à rapprocher, ou lieux à ajouter) :")
        for (nom, ville), k in sorted(absents.items(), key=lambda x: -x[1])[:15]:
            print(f"    {k:>6}  {nom} ({ville})")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sources", nargs="*", help="comptages, evenements, lieux (défaut : les trois)")
    p.add_argument("--comptages", metavar="FICHIER", help="CSV ou Parquet local au lieu du portail")
    p.add_argument("--dataset", default="eco-counter-data", help="jeu du portail pour les comptages")
    p.add_argument("--rafraichir", action="store_true", help="retélécharger les comptages du portail")
    p.add_argument("--evenements", type=Path, default=SECOURS / "evenements_bruts.jsonl", metavar="JSONL")
    p.add_argument("--lieux", type=Path, default=SECOURS / "referentiel_lieux.json", metavar="JSON_OU_CSV")
    a = p.parse_args()
    sources = a.sources or ["comptages", "evenements", "lieux"]
    if inconnues := set(sources) - {"comptages", "evenements", "lieux"}:
        p.error(f"source inconnue : {inconnues}")
    pd.set_option("display.width", 200)

    if "comptages" in sources:
        profiler_comptages(*lire_comptages(a.comptages, a.dataset, a.rafraichir))
    evs = None
    if "evenements" in sources or "lieux" in sources:
        evs, illisibles = lire_evenements(a.evenements) if a.evenements.exists() else ([], 0)
        if "evenements" in sources:
            profiler_evenements(evs, illisibles, a.evenements)
    if "lieux" in sources:
        profiler_lieux(lire_lieux(a.lieux), a.lieux, evs)
