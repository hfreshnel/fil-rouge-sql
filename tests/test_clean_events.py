"""Spécification du nettoyage des événements : votre clean_events.py doit faire passer ces tests.
Lancer depuis la racine du dépôt :  pytest -q
"""
from datetime import datetime, timezone

import pytest

from transform.clean_events import (clean_text, deduplicate, match_venue, normalize_name, run,
                                    validate_and_clean)


def raw(**kw):
    base = {
        "uid": 101,
        "title": {"fr": "Concert de jazz"},
        "description": {"fr": "Un <b>super</b> concert&nbsp;!"},
        "keywords": {"fr": ["Jazz", "concert", "jazz "]},
        "timings": [{"begin": "2026-06-14T20:00:00+02:00", "end": "2026-06-14T23:00:00+02:00"}],
        "location": {"name": "Le 106", "city": "Rouen", "latitude": 49.437, "longitude": 1.078},
        "status": 1,
        "updatedAt": "2026-06-01T10:00:00.000Z",
    }
    base.update(kw)
    return base


def test_clean_text_retire_le_html_et_lit_le_francais():
    assert clean_text({"fr": "Un <b>super</b>   concert&nbsp;!"}) == "Un super concert !"
    assert clean_text(None) == ""


@pytest.mark.parametrize("src, attendu", [
    ("Le 106 – Salle des Musiques Actuelles", "106 musiques actuelles"),
    ("Théâtre  des Arts", "theatre arts"),
    (None, ""),
])
def test_normalize_name(src, attendu):
    assert normalize_name(src) == attendu


@pytest.mark.parametrize("modif, raison", [
    ({"uid": None}, "uid_manquant"),
    ({"title": {"fr": "  <br/> "}}, "titre_vide"),
    ({"timings": []}, "aucune_date"),
    ({"timings": [{"begin": "2026-06-14T23:00:00+02:00", "end": "2026-06-14T20:00:00+02:00"}]}, "dates_incoherentes"),
])
def test_rejets(modif, raison):
    ev, r = validate_and_clean(raw(**modif))
    assert ev is None and r == raison


def test_evenement_valide_est_nettoye():
    ev, r = validate_and_clean(raw())
    assert r is None
    assert ev.title == "Concert de jazz"
    assert ev.keywords == ["concert", "jazz"]
    assert ev.status == "programme"
    assert ev.occurrences[0][0] == datetime(2026, 6, 14, 18, 0, tzinfo=timezone.utc)


def test_geoloc_hors_metropole_mise_a_null_sans_rejet():
    ev, r = validate_and_clean(raw(location={"name": "Le 106", "city": "Rouen", "latitude": 48.85, "longitude": 2.35}))
    assert r is None and ev.lat is None and "geoloc_absente_ou_hors_zone" in ev.flags


def test_doublon_uid_garde_la_version_la_plus_recente():
    old, _ = validate_and_clean(raw(title={"fr": "Ancien titre"}, updatedAt="2026-05-01T00:00:00Z"))
    new, _ = validate_and_clean(raw(updatedAt="2026-06-02T00:00:00Z"))
    kept, rej = deduplicate([new, old])
    assert len(kept) == 1 and kept[0].title == "Concert de jazz"
    assert rej[0]["reason"] == "doublon_uid"


def test_doublon_metier_entre_deux_uids():
    a, _ = validate_and_clean(raw(uid=1))
    b, _ = validate_and_clean(raw(uid=2, location={"name": "LE 106 !", "city": "Rouen",
                                                    "latitude": 49.437, "longitude": 1.078}))
    kept, rej = deduplicate([a, b])
    assert [e.uid for e in kept] == [1] and rej[0]["reason"] == "doublon_metier"


def test_rapprochement_avec_le_referentiel():
    ref = [{"name": "Le 106 - Scène de musiques actuelles", "city": "Rouen", "lat": 49.437, "lon": 1.078},
           {"name": "Théâtre des Arts", "city": "Rouen", "lat": 49.44, "lon": 1.09}]
    assert match_venue(normalize_name("Théatre des arts"), "Rouen", ref)["name"] == "Théâtre des Arts"
    assert match_venue(normalize_name("Salle inconnue"), "Rouen", ref) is None


def test_run_produit_des_statistiques_coherentes():
    res = run([raw(uid=1), raw(uid=1), raw(uid=3, timings=[])], referentiel=[])
    s = res["stats"]
    assert (s["entree"], s["sortie"], s["rejets"]) == (3, 1, 2)
