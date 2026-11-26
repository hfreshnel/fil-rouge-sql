"""Tests du groupe : chargement des comptages vélo (règles de docs/profilage.md). Sans base de données.
Lancer depuis la racine du dépôt :  pytest -q
"""
import struct

import pandas as pd

from chargement.load_comptages import guess, point_wkb, preparer, statut_normalise


def colonnes(df):
    return {k: guess(df, k) for k in ("counter", "name", "ts", "count", "lat", "lon", "location", "status")}


def test_point_wkb_little_endian_et_ewkb():
    # WKB : ordre (1 = little endian), type 1 = Point, puis x = longitude, y = latitude
    wkb = struct.pack("<BIdd", 1, 1, 1.0781, 49.4431)
    assert point_wkb(wkb) == (49.4431, 1.0781)
    # EWKB : drapeau SRID dans le type, puis 4 octets de SRID (4326) avant les coordonnées
    ewkb = struct.pack("<BIIdd", 1, 0x20000001, 4326, 1.0781, 49.4431)
    assert point_wkb(ewkb) == (49.4431, 1.0781)
    assert point_wkb(b"pas un point") is None


def test_statut_normalise_deux_formats():
    assert statut_normalise("Donnée brut") == "brut"
    assert statut_normalise("Donnée corrigée") == "corrige"
    assert statut_normalise('["validated"]') == "valide"
    assert statut_normalise('["deleted", "validated"]') == "supprime"
    assert statut_normalise('["modified", "deleted"]') == "supprime"
    assert statut_normalise(None) is None


def test_doublon_garde_la_ligne_non_supprimee_sans_additionner():
    # Cas réel du profilage : Eco 29, une ligne deleted vide et une ligne « Donnée corrigée » à 4 pour la même heure
    df = pd.DataFrame({
        "id": ["29", "29", "29"],
        "name": ["Eco 29"] * 3,
        "date": ["2025-03-30T01:00:00+00:00", "2025-03-30T01:00:00+00:00", "2025-03-30T02:00:00+00:00"],
        "counts": [None, 4.0, 7.0],
        "status": ['["deleted", "validated"]', "Donnée corrigée", "Donnée brut"],
    })
    heures, _, rejets = preparer(df, colonnes(df))
    assert heures["passages"].tolist() == [4, 7]     # 4 et non 4 + 0 : pas de somme
    assert heures["status"].tolist() == ["corrige", "brut"]
    assert rejets["raison"].tolist() == ["supprimée à la source"]


def test_doublon_restant_garde_la_version_la_plus_fiable():
    df = pd.DataFrame({
        "id": ["1", "1"],
        "date": ["2025-01-01T08:00:00+00:00"] * 2,
        "counts": [10.0, 12.0],
        "status": ["Donnée brut", '["validated"]'],
    })
    heures, _, rejets = preparer(df, colonnes(df))
    assert heures[["passages", "status"]].values.tolist() == [[12, "valide"]]
    assert rejets["raison"].str.startswith("doublon").all()


def test_jeu_synthetique_avec_latitude_longitude():
    df = pd.DataFrame({
        "id_compteur": ["CPT-001", "CPT-001"],
        "nom_compteur": ["Pont Boieldieu"] * 2,
        "date": ["2025-01-01T00:00:00+00:00", "2025-01-01T01:00:00+00:00"],
        "comptage": [2.0, 1.0],
        "latitude": [49.4372] * 2,
        "longitude": [1.0869] * 2,
    })
    heures, compteurs, rejets = preparer(df, colonnes(df))
    assert len(heures) == 2 and rejets.empty
    assert heures["status"].isna().all()             # pas de colonne status : NULL, pas d'invention
    assert compteurs[["counter_id", "lat", "lon"]].values.tolist() == [["CPT-001", 49.4372, 1.0869]]
