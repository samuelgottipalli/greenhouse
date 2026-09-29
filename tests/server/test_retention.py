"""
Tests for the monthly summaries and clean-up (core/history.py, scripts/retention.py):
month arithmetic, the statistics, summarising finished months, deleting raw
readings older than 6 months only once they are summarised, catching up, and
the Analysis page's year view.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pandas import Series

from core import db, history
from scripts import retention as retention_script

ZONE = "America/Los_Angeles"
NOW = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)  # 1 Oct, 03:30 in Sparks


@pytest.fixture(autouse=True)
def clean(seeded_db, db_conn):
    """Start without the shared fixture's readings; the tests add their own."""
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.execute("DELETE FROM weather_readings")
    db_conn.commit()


def month_of_readings(db_conn, month, values, measure_id=1, device=1):
    """One reading a day at local noon (19:00 UTC in summer), values in turn."""
    start = datetime(int(month[:4]), int(month[5:]), 1, 19, 0)
    db_conn.executemany("INSERT INTO sensor_readings VALUES (?, ?, ?, ?)",
                        [(device, measure_id, (start + timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S"), v)
                         for i, v in enumerate(values)])
    db_conn.commit()


def weather_rows(db_conn, rows):
    """(measured_utc, temperature_c, precipitation_mm)."""
    db_conn.executemany(
        "INSERT INTO weather_readings (measured_utc, latitude, longitude, temperature_c, relative_humidity_pct, "
        "precipitation_mm, wind_speed_kmh) VALUES (?, 39.53, -119.75, ?, 50, ?, 5)", rows)
    db_conn.commit()


def count(db_conn, table):
    return db_conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# --- months and statistics ---------------------------------------------------------------


@pytest.mark.parametrize("month, n, expected", [("2026-10", -6, "2026-04"), ("2026-01", -1, "2025-12"),
                                                ("2025-12", 1, "2026-01"), ("2026-03", -15, "2024-12")])
def test_add_months(month, n, expected):
    assert history.add_months(month, n) == expected


def test_month_range_and_bounds():
    assert history.month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert history.month_bounds("2026-03", ZONE) == ("2026-03-01 08:00:00", "2026-04-01 07:00:00")  # DST starts
    assert history.current_month(NOW, ZONE) == "2026-10"
    assert history.current_month(datetime(2026, 10, 1, 5, 0, tzinfo=timezone.utc), ZONE) == "2026-09"  # still Sep


def test_statistics():
    stats = history.statistics(Series(range(1, 101)), with_total=True)
    assert (stats["samples"], stats["mean"], stats["median"], stats["minimum"], stats["maximum"]) == (100, 50.5, 50.5, 1, 100)
    assert (stats["p25"], stats["p75"]) == (25.75, 75.25)
    assert (stats["p2_5"], stats["p97_5"]) == (3.475, 97.525)
    assert stats["total"] == 5050
    assert history.statistics(Series([1.0, 2.0]))["total"] is None
    assert history.statistics(Series([], dtype=float)) is None


def test_light_is_summarised_in_lux(db_conn):
    from core.light import raw_to_lux

    month_of_readings(db_conn, "2026-08", [30000, 30000], measure_id=6)
    stats = history.month_statistics("greenhouse", 1, "light", "2026-08", ZONE)
    assert stats["median"] == pytest.approx(round(raw_to_lux(30000), 3))


def test_rain_is_summarised_as_daily_totals(db_conn):
    weather_rows(db_conn, [("2026-08-01 18:00:00", 20, 1.0), ("2026-08-01 18:15:00", 20, 2.0),
                           ("2026-08-02 18:00:00", 20, 0.5)])
    stats = history.month_statistics("weather", 0, "rain", "2026-08", ZONE)
    assert (stats["samples"], stats["maximum"], stats["total"]) == (2, 3.0, 3.5)


# --- the monthly job -----------------------------------------------------------------------


@pytest.fixture
def year_of_data(db_conn):
    for number in range(1, 10):  # January to September 2026
        month = f"2026-{number:02d}"
        month_of_readings(db_conn, month, [10.0 + number, 20.0 + number, 30.0 + number])
        weather_rows(db_conn, [(f"{month}-10 19:00:00", number, 1.0)])


def test_run_monthly_summarises_then_trims(db_conn, year_of_data, tmp_path):
    report = history.run_monthly(NOW, zone=ZONE, backup_dir=tmp_path)
    assert report["ok"]
    assert "greenhouse/1/temperature/2026-01" in report["summarised"]
    assert "weather/0/rain/2026-09" in report["summarised"]
    # Kept raw: April to September (6 whole months before October); deleted: January to March.
    assert report["cutoff_utc"] == "2026-04-01 07:00:00"
    assert report["deleted"] == {"sensor_rows": 9, "weather_rows": 3}
    assert db_conn.execute("SELECT min(reading_utc) FROM sensor_readings").fetchone()[0] >= "2026-04-01"
    kept = history.stored("greenhouse", 1, "temperature", "2026-01", "2026-09")
    assert list(kept["month"]) == [f"2026-{n:02d}" for n in range(1, 10)]
    january = kept.iloc[0]
    assert (january["samples"], january["median"], january["minimum"], january["maximum"]) == (3, 21.0, 11.0, 31.0)
    assert (tmp_path / "before-monthly-trim-2026-10.db").exists()
    assert history.last_run() == {"month": "2026-09", "utc": "2026-10-01 10:30:00", "result": "ok"}


def test_run_monthly_twice_does_nothing_new(db_conn, year_of_data, tmp_path):
    history.run_monthly(NOW, zone=ZONE, backup_dir=tmp_path)
    rows = count(db_conn, "monthly_stats")
    again = history.run_monthly(NOW + timedelta(hours=1), zone=ZONE, backup_dir=tmp_path)
    assert again["summarised"] == [] and again["deleted"] is None and again["ok"]
    assert count(db_conn, "monthly_stats") == rows


def test_missed_first_is_caught_up_later(db_conn, year_of_data, tmp_path):
    """The computer was off on the 1st: the run at the next start does the same work."""
    late = history.run_monthly(NOW + timedelta(days=9), zone=ZONE, backup_dir=tmp_path)
    assert "greenhouse/1/temperature/2026-09" in late["summarised"] and late["deleted"]["sensor_rows"] == 9


def test_nothing_is_deleted_when_a_summary_fails(db_conn, year_of_data, tmp_path, monkeypatch):
    monkeypatch.setattr(history, "save", lambda *args, **kwargs: False)
    report = history.run_monthly(NOW, zone=ZONE, backup_dir=tmp_path)
    assert not report["ok"] and report["deleted"] is None
    assert count(db_conn, "sensor_readings") == 27
    assert history.last_run()["result"] == "failed"


def test_nothing_to_do_on_an_empty_database(tmp_path):
    report = history.run_monthly(NOW, zone=ZONE, backup_dir=tmp_path)
    assert report == {"summarised": [], "deleted": None, "cutoff_utc": "2026-04-01 07:00:00", "backup": None,
                      "ok": True}


def test_only_the_newest_backups_are_kept(db_conn, tmp_path):
    for month in ("2026-06", "2026-07", "2026-08", "2026-09"):
        history.backup(tmp_path, month)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "before-monthly-trim-2026-07.db", "before-monthly-trim-2026-08.db", "before-monthly-trim-2026-09.db"]


def test_script(db_conn, year_of_data, capsys, monkeypatch):
    real = history.run_monthly
    monkeypatch.setattr(history, "run_monthly", lambda keep_months: real(NOW, keep_months, ZONE))
    assert retention_script.main([]) == 0
    out = capsys.readouterr().out
    assert "Summarised" in out and "Deleted readings before 2026-04-01 07:00:00 UTC: 9 greenhouse, 3 weather" in out
    assert retention_script.main([]) == 0
    assert "Nothing older than" in capsys.readouterr().out


# --- the year view (Analysis page) --------------------------------------------------------


def test_year_view(db_conn, year_of_data, tmp_path):
    history.run_monthly(NOW, zone=ZONE, backup_dir=tmp_path)
    month_of_readings(db_conn, "2026-10", [5.0])  # this month so far (1 Oct, 19:00 UTC)
    view = history.year_view("greenhouse", 1, "temperature", NOW + timedelta(hours=12), ZONE)
    assert list(view["month"]) == [f"2026-{n:02d}" for n in range(1, 11)]
    assert list(view["live"]) == [False] * 9 + [True]
    assert view.iloc[-1]["median"] == 5.0
    assert view.iloc[0]["median"] == 21.0  # January: from the summary, its raw readings are gone


def test_year_view_works_before_the_first_monthly_run(db_conn, year_of_data):
    """Finished months not summarised yet are worked out from their raw readings."""
    view = history.year_view("greenhouse", 1, "temperature", NOW, ZONE)
    assert len(view) == 9 and not view["live"].any()
    assert history.year_view("greenhouse", 2, "temperature", NOW, ZONE) is None
