"""
Tests for report periods (core/periods.py, ui.period_picker), the Outdoor
weather history (db.weather_history, weather_report.history_frames) and the
Analysis page (sections/analysis.py).
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pandas import DataFrame, Timestamp
from streamlit.testing.v1 import AppTest

from core import db, history, periods
from support import SERVER_DIR, run_section, section_app

ZONE = "America/Los_Angeles"


# --- periods -------------------------------------------------------------------------------


def test_presets():
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    week = periods.preset("7 days", now)
    assert (week.since_utc, week.days, week.detail, week.rain_step) == ("2026-09-22 12:00:00", 7, "hour", "hour")
    assert periods.preset("24 hours", now).detail == "raw"
    month = periods.preset("30 days", now)
    assert (month.detail, month.rain_step) == ("hour", "day")


def test_date_range_is_whole_local_days():
    period = periods.date_range(date(2026, 3, 1), date(2026, 8, 31), ZONE)
    assert (period.since_utc, period.until_utc) == ("2026-03-01 08:00:00", "2026-09-01 07:00:00")
    assert period.days == 184 and period.detail == "day" and period.label == "Mar 1 – Aug 31, 2026"
    assert periods.date_range(date(2026, 9, 5), date(2026, 9, 5), ZONE).label == "Sep 5, 2026"
    swapped = periods.date_range(date(2026, 9, 10), date(2026, 9, 1), ZONE)
    assert swapped.since_utc == "2026-09-01 07:00:00" and swapped.days == 10
    assert periods.date_range(date(2025, 12, 20), date(2026, 1, 5), ZONE).label == "Dec 20, 2025 – Jan 5, 2026"


@pytest.mark.parametrize("days, detail", [(1, "raw"), (2, "raw"), (3, "hour"), (45, "hour"), (46, "day")])
def test_detail_by_length(days, detail):
    assert periods.Period("x", "a", "b", days).detail == detail


# --- queries --------------------------------------------------------------------------------


@pytest.fixture
def weather(seeded_db, db_conn):
    db_conn.execute("DELETE FROM weather_readings")
    rows = [("2026-09-28 17:00:00", 39.53, -119.75, 20.0, 40.0, 0.5, 10.0),
            ("2026-09-28 17:15:00", 39.53, -119.75, 22.0, 42.0, 0.25, 12.0),
            ("2026-09-29 18:00:00", 39.53, -119.75, 30.0, 30.0, 0.0, 5.0),
            ("2026-09-28 17:30:00", 51.50, -0.12, 10.0, 90.0, 9.0, 40.0)]  # another place
    db_conn.executemany("INSERT INTO weather_readings (measured_utc, latitude, longitude, temperature_c, "
                        "relative_humidity_pct, precipitation_mm, wind_speed_kmh) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    db_conn.commit()


SPARKS = {"latitude": 39.5349, "longitude": -119.7527}


def test_weather_history_raw_and_hourly(weather):
    raw = db.weather_history("2026-09-28 00:00:00", "2026-09-30 00:00:00", place=SPARKS)
    assert list(raw["temperature_c"]) == [20.0, 22.0, 30.0]
    hourly = db.weather_history("2026-09-28 00:00:00", "2026-09-30 00:00:00", hourly=True, place=SPARKS)
    first = hourly.iloc[0]
    assert (first["measured_utc"], first["temperature_c"], first["precipitation_mm"]) == ("2026-09-28 17:00:00", 21.0, 0.75)
    assert len(db.weather_history("2026-09-28 00:00:00", "2026-09-30 00:00:00")) == 4  # every place


def test_sensor_history_until_and_first_reading(seeded_db):
    assert db.first_reading_utc("greenhouse", 1) == "2025-10-21 22:38:12"
    upto = db.sensor_history("2025-01-01 00:00:00", device_id=1, until_utc="2025-10-22 00:00:00")
    assert list(upto["reading_utc"]) == ["2025-10-21 22:38:12"]
    assert db.first_reading_utc("greenhouse", 9) is None


def test_history_frames(weather):
    data = db.weather_history("2026-09-28 00:00:00", "2026-09-30 00:00:00", place=SPARKS)
    measures, rain = __import__("core.weather_report", fromlist=["x"]).history_frames(data, "US", ZONE, "day", "day")
    assert list(measures["time"]) == [Timestamp("2026-09-28"), Timestamp("2026-09-29")]
    assert measures.iloc[0]["temperature_c"] == pytest.approx(69.8)  # 21 °C
    assert list(rain["rain"]) == [pytest.approx(0.03), 0.0]  # 0.75 mm, in inches
    measures, rain = __import__("core.weather_report", fromlist=["x"]).history_frames(data, "SI", ZONE, "raw", "hour")
    assert len(measures) == 3 and list(rain["rain"]) == [0.75, 0.0]  # per hour


# --- pages ----------------------------------------------------------------------------------


def with_date_range(section, first, last):
    """
    Run a report tab once with "Date range" and the dates already chosen.

    Set through session state before the only run: AppTest (Streamlit 1.50)
    mishandles a single-choice segmented control's multi-letter value when the
    page runs again after it is chosen.
    """
    at = section_app(section)
    at.session_state[f"{section}_period"] = periods.DATE_RANGE
    at.session_state[f"{section}_range"] = (first, last)
    return at.run()


def test_weather_tab_has_a_history(seeded_db):
    """The fixture's readings are at today's local noon, so a range through today holds them."""
    at = run_section("weather")
    assert not at.exception, [e.message for e in at.exception]
    assert any(m.value == "#### History" for m in at.markdown)
    today = datetime.now(ZoneInfo(ZONE)).date()
    at = with_date_range("weather", today - timedelta(days=1), today)
    assert not at.exception, [e.message for e in at.exception]
    label = periods.date_range(today - timedelta(days=1), today, ZONE).label
    titles = [m.value for m in at.markdown if m.value.startswith("**") and "·" in m.value]
    assert titles == [f"**{name}** · {label}" for name in ("Temperature", "Humidity", "Rain", "Wind speed")]
    assert any(c.value.startswith("Total ") for c in at.caption)  # rain
    assert at.date_input and "6 months" in " ".join(c.value for c in at.caption)


def test_greenhouse_date_range_shows_that_range(seeded_db):
    at = with_date_range("greenhouse", date(2025, 10, 21), date(2025, 10, 23))
    assert not at.exception, [e.message for e in at.exception]
    assert "**Temperature** · Oct 21 – Oct 23, 2025" in [m.value for m in at.markdown]
    assert any(c.value.startswith("High ") for c in at.caption)


def test_long_range_uses_daily_averages(seeded_db):
    at = with_date_range("greenhouse", date(2025, 9, 1), date(2025, 12, 31))
    assert not at.exception, [e.message for e in at.exception]
    assert "Daily averages." in [c.value for c in at.caption]


# --- Analysis ---------------------------------------------------------------------------------


def test_analysis_prepare_and_compare():
    from sections import analysis

    view = DataFrame([
        {"month": "2025-09", "samples": 30, "mean": 20.0, "median": 20.0, "p2_5": 10.0, "p25": 15.0, "p75": 25.0,
         "p97_5": 30.0, "minimum": 9.0, "maximum": 31.0, "total": None, "live": False},
        {"month": "2026-09", "samples": 10, "mean": 22.0, "median": 21.0, "p2_5": 12.0, "p25": 16.0, "p75": 26.0,
         "p97_5": 32.0, "minimum": 11.0, "maximum": 33.0, "total": None, "live": True},
    ])
    frame = analysis.prepare(view, "temperature", "US", "2026-09")
    assert list(frame["group"]) == [analysis.LAST_YEAR, analysis.THIS_MONTH]
    assert list(frame["label"]) == ["Sep 25", "Sep 26"] and frame.iloc[0]["median"] == 68.0
    assert analysis.decimals_for("humidity", "US") == 0 and analysis.decimals_for("rain", "US") == 2
    sentence = analysis.comparison(frame, "°F", rain=False)
    assert sentence.startswith("September so far: median 69.8 °F") and "1.8 °F higher than last September" in sentence
    chart = analysis.box_chart(frame, "°F").to_dict()
    assert len(chart["layer"]) == 4  # whiskers, box, median, average
    light = analysis.box_chart(frame, "lux", log=True).to_dict()
    assert light["layer"][0]["encoding"]["y"]["scale"]["type"] == "symlog"
    table = analysis.stats_table(frame, "°F", rain=False)
    assert table.iloc[0]["Month"] == "Sep 26" and "97.5th %" in table.columns


def test_analysis_rain_sentence():
    from sections import analysis

    frame = DataFrame([{"month": "2026-09", "total": 12.5, "group": analysis.THIS_MONTH}])
    assert analysis.comparison(frame, "mm", rain=True) == "September so far: 12.5 mm of rain. No figures for last year yet."


def test_analysis_page(seeded_db, db_conn):
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    db_conn.execute("INSERT INTO sensor_readings VALUES (1, 1, ?, 21.0)", (stamp,))
    db_conn.commit()
    history.save("greenhouse", 1, "temperature", history.add_months(history.current_month(), -12),
                 {"samples": 100, "mean": 19.0, "median": 19.5, "p2_5": 12, "p25": 16, "p75": 23, "p97_5": 28,
                  "minimum": 10, "maximum": 30, "total": None})
    at = AppTest.from_file(str(SERVER_DIR / "views/analysis.py"), default_timeout=60).run()
    assert not at.exception, [e.message for e in at.exception]
    assert [t.label for t in at.tabs] == ["Greenhouse", "Outdoor weather"]
    greenhouse = at.tabs[0]
    assert len(greenhouse.get("arrow_vega_lite_chart")) >= 1
    assert any("so far: median" in c.value and "than last" in c.value for c in greenhouse.caption)
