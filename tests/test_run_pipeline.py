
import json
import sys

import etl.run_pipeline as pipeline
from etl.run_pipeline import save_jsonl


def test_save_jsonl_creates_file(tmp_path):
    path = tmp_path / "quarantaine.jsonl"
    rows = [
        {"uid": 123, "reason": "titre_manquant"},
        {"uid": 456, "reason": "date_invalide"},
    ]

    save_jsonl(str(path), rows)

    assert path.exists()

    content = path.read_text(encoding="utf-8").splitlines()

    assert len(content) == 2
    assert '"uid": 123' in content[0]
    assert '"reason": "date_invalide"' in content[1]


def test_save_jsonl_empty_list(tmp_path):
    path = tmp_path / "quarantaine.jsonl"

    save_jsonl(str(path), [])

    assert path.exists()
    assert path.read_text(encoding="utf-8") == ""


def test_pipeline_success_without_database_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "referentiel_ban.json").write_text(
        "[]", encoding="utf-8"
    )

    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--no-load"])
    monkeypatch.setattr(pipeline, "load_dotenv", lambda: None)
    monkeypatch.setattr(pipeline, "configure_logging", lambda: None)
    monkeypatch.setattr(pipeline, "load_jsonl", lambda path: [{"uid": 1}])
    monkeypatch.setattr(
        pipeline,
        "run",
        lambda events, ref: {
            "events": [],
            "rejected": [],
            "stats": {"entree": 1, "sortie": 0, "rejets": 1},
        },
    )
    monkeypatch.setattr(
        pipeline,
        "check_quality",
        lambda events, rejected: {
            "passed": True,
            "metrics": {"total": 1, "valid": 0, "rejected": 1},
            "errors": [],
            "warnings": [],
        },
    )

    result = pipeline.main()

    report = json.loads(
        (tmp_path / "run_report.json").read_text(encoding="utf-8")
    )

    assert result == 0
    assert report["status"] == "success"
    assert report["collection_cleaning"]["entree"] == 1

def test_pipeline_fails_when_quality_check_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "referentiel_ban.json").write_text(
        "[]", encoding="utf-8"
    )

    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--no-load"])
    monkeypatch.setattr(pipeline, "load_dotenv", lambda: None)
    monkeypatch.setattr(pipeline, "configure_logging", lambda: None)
    monkeypatch.setattr(pipeline, "load_jsonl", lambda path: [{"uid": 1}])
    monkeypatch.setattr(
        pipeline,
        "run",
        lambda events, ref: {
            "events": [],
            "rejected": [],
            "stats": {"entree": 1, "sortie": 0, "rejets": 1},
        },
    )
    monkeypatch.setattr(
        pipeline,
        "check_quality",
        lambda events, rejected: {
            "passed": False,
            "metrics": {"total": 1, "valid": 0, "rejected": 1},
            "errors": [{"reason": "qualite_invalide"}],
            "warnings": [],
        },
    )

    result = pipeline.main()

    report = json.loads(
        (tmp_path / "run_report.json").read_text(encoding="utf-8")
    )

    assert result == 1
    assert report["status"] == "failed"
    assert "error" in report
    
def test_pipeline_fails_when_input_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(sys, "argv", ["run_pipeline.py", "--no-load"])
    monkeypatch.setattr(pipeline, "load_dotenv", lambda: None)
    monkeypatch.setattr(pipeline, "configure_logging", lambda: None)

    result = pipeline.main()

    report = json.loads(
        (tmp_path / "run_report.json").read_text(encoding="utf-8")
    )

    assert result == 1
    assert report["status"] == "failed"
    assert "error" in report