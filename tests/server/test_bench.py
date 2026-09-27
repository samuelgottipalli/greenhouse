"""Smoke test for server/scripts/bench.py (S-10): runs on a small synthetic database."""
from core import db, settings
from scripts import bench


def test_bench_runs_and_meets_target_on_small_data(capsys, seeded_db):
    original_url = settings.DB_URL
    assert bench.main(["--days", "3", "--runs", "2"]) == 0
    assert settings.DB_URL == original_url
    out = capsys.readouterr().out
    assert "latest_sensor_readings" in out and "SLOW" not in out
    # The benchmark must not leave the app pointing at its throwaway database.
    assert db.latest_relay_states() is not None


def test_bench_with_several_devices(seeded_db, capsys):
    assert bench.main(["--days", "2", "--runs", "1", "--devices", "3"]) == 0
    assert "3 device(s)" in capsys.readouterr().out
