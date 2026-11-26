
from collecte.openagenda_collector import monthly_windows, pending_windows


def test_monthly_windows():
    windows = monthly_windows("2026-01", "2026-03")

    assert len(windows) == 3

    assert windows[0] == (
        "2026-01-01T00:00:00",
        "2026-01-31T23:59:59",
    )

    assert windows[1] == (
        "2026-02-01T00:00:00",
        "2026-02-28T23:59:59",
    )

    assert windows[2] == (
        "2026-03-01T00:00:00",
        "2026-03-31T23:59:59",
    )



def test_pending_windows():
    windows = [
        ("2026-01-01T00:00:00", "2026-01-31T23:59:59"),
        ("2026-02-01T00:00:00", "2026-02-28T23:59:59"),
        ("2026-03-01T00:00:00", "2026-03-31T23:59:59"),
    ]

    completed = ["2026-01", "2026-02"]

    pending = pending_windows(windows, completed)

    assert pending == [
        ("2026-03-01T00:00:00", "2026-03-31T23:59:59")
    ]
    
def test_save_and_load_checkpoint(tmp_path):
    from collecte.openagenda_collector import load_checkpoint, save_checkpoint

    path = tmp_path / "checkpoint.json"
    months = ["2026-01", "2026-02"]

    save_checkpoint(
        str(path), months,
        "rouen-normandie-metropole", "2026-01", "2026-03"
    )

    assert load_checkpoint(
        str(path),
        "rouen-normandie-metropole", "2026-01", "2026-03"
    ) == months

def test_load_checkpoint_when_file_does_not_exist(tmp_path):
    from collecte.openagenda_collector import load_checkpoint

    path = tmp_path / "checkpoint.json"

    assert load_checkpoint(
        str(path),
        "rouen-normandie-metropole", "2026-01", "2026-03"
    ) == []
    

def test_merge_monthly_files(tmp_path):
    from collecte.openagenda_collector import merge_monthly_files

    data_dir = tmp_path / "openagenda"
    data_dir.mkdir()

    (data_dir / "2026-01.jsonl").write_text(
        '{"id": 1}\n',
        encoding="utf-8"
    )
    (data_dir / "2026-02.jsonl").write_text(
        '{"id": 2}\n',
        encoding="utf-8"
    )

    output = tmp_path / "evenements_bruts.jsonl"

    windows = [
        ("2026-01-01", "2026-02-01"),
        ("2026-02-01", "2026-03-01"),
    ]

    merge_monthly_files(windows, str(output), str(data_dir))

    lines = output.read_text(encoding="utf-8").splitlines()

    assert lines == ['{"id": 1}', '{"id": 2}']
    

def test_checkpoint_incompatible(tmp_path):
    from collecte.openagenda_collector import load_checkpoint, save_checkpoint

    path = tmp_path / "checkpoint.json"

    save_checkpoint(
        str(path), ["2026-01"],
        "rouen-normandie-metropole", "2026-01", "2026-03"
    )

    assert load_checkpoint(
        str(path),
        "rouen-normandie-metropole", "2026-01", "2026-04"
    ) == []
    
def test_failed_collection_does_not_validate_month(tmp_path, monkeypatch):
    import asyncio
    import collecte.openagenda_collector as collector

    async def fake_collect_window(session, sem, uid, gte, lt, queue):
        raise RuntimeError("Erreur simulée")

    monkeypatch.setattr(
        collector, "collect_window", fake_collect_window
    )

    output = tmp_path / "2026-01.jsonl"
    checkpoint = tmp_path / "checkpoint.json"

    async def run():
        await collector.collect_and_save_window(
            None, None, 123,
            "2026-01-01", "2026-02-01",
            str(output), str(checkpoint), [],
            asyncio.Lock(),
            "rouen-normandie-metropole",
            "2026-01", "2026-02"
        )

    try:
        asyncio.run(run())
        assert False, "Une erreur était attendue"
    except RuntimeError:
        pass

    assert not output.exists()
    assert not checkpoint.exists()