"""Tests for data retention (PLAN 3.4): core/retention.py and scripts/retention.py."""
from datetime import datetime, timezone

import pytest

from core import db, retention
from scripts import retention as retention_script


@pytest.fixture(autouse=True)
def no_fixture_readings(seeded_db, db_conn):
    """Start without the shared fixture's 2025 readings, which would be rolled up too."""
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.commit()


def add(db_conn, rows, measure_id=1):
    db_conn.executemany("INSERT INTO sensor_readings VALUES (1, ?, ?, ?)", [(measure_id, at, v) for at, v in rows])
    db_conn.commit()


def rows_between(db_conn, start, end, measure_id=1):
    return db_conn.execute(
        "SELECT reading_utc, value FROM sensor_readings WHERE measure_id = ? AND reading_utc >= ? "
        "AND reading_utc < ? ORDER BY reading_utc", (measure_id, start, end)
    ).fetchall()


def test_cutoff_is_rounded_to_the_hour():
    now = datetime(2026, 9, 26, 19, 47, 12, tzinfo=timezone.utc)
    assert retention.cutoff_for(90, now) == "2026-06-28 19:00:00"


def test_old_readings_become_hourly_averages(seeded_db, db_conn):
    add(db_conn, [("2026-01-01 10:05:00", 20.0), ("2026-01-01 10:35:00", 22.0),
                  ("2026-01-01 11:00:00", 30.0), ("2026-01-01 11:30:00", 32.0),
                  ("2026-06-01 10:05:00", 50.0)])
    result = retention.roll_up("2026-02-01 00:00:00")
    assert result["added"] == 2
    assert rows_between(db_conn, "2026-01-01", "2026-01-02") == [
        ("2026-01-01 10:00:00", 21.0),
        ("2026-01-01 11:00:00", 31.0),  # the raw 11:00:00 reading was replaced by the average
    ]
    assert rows_between(db_conn, "2026-06-01", "2026-06-02") == [("2026-06-01 10:05:00", 50.0)]  # recent: untouched


def test_hour_at_cutoff_is_not_split(seeded_db, db_conn):
    add(db_conn, [("2026-01-01 09:55:00", 10.0), ("2026-01-01 10:05:00", 20.0), ("2026-01-01 10:35:00", 22.0)])
    retention.roll_up("2026-01-01 10:00:00")
    assert rows_between(db_conn, "2026-01-01", "2026-01-02") == [
        ("2026-01-01 09:00:00", 10.0),
        ("2026-01-01 10:05:00", 20.0),
        ("2026-01-01 10:35:00", 22.0),
    ]


def test_running_twice_changes_nothing(seeded_db, db_conn):
    add(db_conn, [("2026-01-01 10:05:00", 20.0), ("2026-01-01 10:35:00", 22.0)])
    retention.roll_up("2026-02-01 00:00:00")
    before = db_conn.execute("SELECT * FROM sensor_readings ORDER BY 1, 2, 3").fetchall()
    assert retention.roll_up("2026-02-01 00:00:00") == {"removed": 0, "added": 0, "weather_removed": 0}
    assert db_conn.execute("SELECT * FROM sensor_readings ORDER BY 1, 2, 3").fetchall() == before


def test_measures_are_averaged_separately(seeded_db, db_conn):
    add(db_conn, [("2026-01-01 10:05:00", 20.0), ("2026-01-01 10:35:00", 22.0)], measure_id=1)
    add(db_conn, [("2026-01-01 10:05:00", 40.0), ("2026-01-01 10:35:00", 60.0)], measure_id=8)
    retention.roll_up("2026-02-01 00:00:00")
    assert rows_between(db_conn, "2026-01-01", "2026-01-02", 8) == [("2026-01-01 10:00:00", 50.0)]


def test_chart_values_are_unchanged_by_retention(seeded_db, db_conn):
    add(db_conn, [(f"2026-01-01 {h:02d}:{m:02d}:00", float(h * 10 + m)) for h in range(10, 14) for m in (5, 20, 35, 50)])
    before = db.sensor_history("2026-01-01 00:00:00", bucket="hour")
    retention.roll_up("2026-02-01 00:00:00")
    after = db.sensor_history("2026-01-01 00:00:00", bucket="hour")
    assert before.values.tolist() == after.values.tolist()


def test_old_weather_keeps_hourly_snapshots(seeded_db, db_conn):
    db_conn.execute("DELETE FROM weather_readings")
    for minute in ("00", "15", "30", "45"):
        db_conn.execute(
            "INSERT INTO weather_readings (measured_utc, latitude, longitude) VALUES (?, 1, 2)",
            (f"2026-01-01 10:{minute}:00",),
        )
    db_conn.commit()
    assert retention.roll_up("2026-02-01 00:00:00")["weather_removed"] == 3
    assert db_conn.execute("SELECT measured_utc FROM weather_readings").fetchall() == [("2026-01-01 10:00:00",)]


def test_script_run_reports_and_vacuums(seeded_db, db_conn, capsys, monkeypatch):
    add(db_conn, [("2020-01-01 10:05:00", 20.0), ("2020-01-01 10:35:00", 22.0)])
    vacuumed = []
    monkeypatch.setattr(retention, "vacuum", lambda: vacuumed.append(1) or True)
    assert retention_script.main([]) == 0
    assert "2 raw rows -> 1 hourly rows" in capsys.readouterr().out
    assert vacuumed == [1]


def test_vacuum_runs(seeded_db):
    assert retention.vacuum() is True


def test_measure_on_small_synthetic_data(monkeypatch, capsys):
    from scripts import bench

    real_fill = bench.fill
    monkeypatch.setattr(bench, "fill", lambda path, days: real_fill(path, days // 36))  # ~10 and ~20 days
    growth = retention_script.measure(keep_days=3)
    assert growth > 0
    assert "MB per year per device" in capsys.readouterr().out
