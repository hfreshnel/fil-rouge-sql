from datetime import datetime, timezone

from etl.quality import check_quality
from transform.clean_events import CleanEvent


def make_event(**overrides):
    """Construit un événement valide pour les tests."""
    event = CleanEvent(
        uid=12345,
        title="Festival de Rouen",
        description="Un événement culturel",
        keywords=["culture"],
        status="programme",
        updated_at=None,
        venue_name="Zénith",
        venue_norm="zenith",
        city="Rouen",
        lat=49.4432,
        lon=1.0993,
        occurrences=[
            (
                datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
                datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)
            )
        ]
    )

    for key, value in overrides.items():
        setattr(event, key, value)

    return event


def test_valid_event_passes():
    event = make_event()

    result = check_quality([event], [])

    assert result["passed"] is True
    assert result["metrics"]["valid"] == 1
    assert result["metrics"]["errors"] == 0


def test_missing_title_is_detected():
    event = make_event(title="")

    result = check_quality([event], [])

    assert result["passed"] is False
    assert any(
        error["reason"] == "titre_manquant"
        for error in result["errors"]
    )

def test_duplicate_uid_is_detected():
    event1 = make_event()
    event2 = make_event(title="Autre événement")

    result = check_quality([event1, event2], [])

    assert result["passed"] is False
    assert any(
        error["reason"] == "identifiant_duplique"
        for error in result["errors"]
    )


def test_missing_geolocation_is_warning():
    event = make_event(lat=None, lon=None)

    result = check_quality([event], [])

    assert result["passed"] is True
    assert any(
        warning["reason"] == "geolocalisation_absente"
        for warning in result["warnings"]
    )


def test_coordinates_outside_zone_are_detected():
    event = make_event(lat=48.0, lon=2.0)

    result = check_quality([event], [])

    assert result["passed"] is False
    assert any(
        error["reason"] == "coordonnees_hors_zone"
        for error in result["errors"]
    )