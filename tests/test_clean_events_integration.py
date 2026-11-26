from transform.clean_events import run


def test_run_rapproche_le_lieu_et_recupere_ses_coordonnees():
    raw_event = {
        "uid": 501,
        "title": {"fr": "Concert de jazz"},
        "description": {"fr": "Un concert à Rouen"},
        "keywords": {"fr": ["jazz"]},
        "timings": [
            {
                "begin": "2026-06-14T18:00:00Z",
                "end": "2026-06-14T20:00:00Z"
            }
        ],
        "location": {
            "name": "Le 106",
            "city": "Rouen",
            "latitude": None,
            "longitude": None
        },
        "status": 1,
        "updatedAt": "2026-06-01T10:00:00Z"
    }

    referentiel = [
        {
            "name": "Le 106",
            "city": "Rouen",
            "lat": 49.437,
            "lon": 1.078
        }
    ]

    resultat = run([raw_event], referentiel)

    assert resultat["stats"]["entree"] == 1
    assert resultat["stats"]["sortie"] == 1
    assert resultat["stats"]["rejets"] == 0

    evenement = resultat["events"][0]

    assert evenement.venue_name == "Le 106"
    assert evenement.lat == 49.437
    assert evenement.lon == 1.078
    assert "geoloc_depuis_referentiel" in evenement.flags
