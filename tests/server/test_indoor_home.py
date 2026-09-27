"""Tests for the Home and Greenhouse Weather pages and core/indoor_report.py (S-15)."""
from datetime import datetime, timedelta, timezone

import pytest
from pandas import DataFrame

from core.indoor_report import age_text, display_value, history_by_measure, is_stale
from core.timeutil import utc_timestamp
from support import SERVER_DIR
from streamlit.testing.v1 import AppTest

NOW = datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc)


def run_page(page):
    return AppTest.from_file(str(SERVER_DIR / page), default_timeout=30).run()


def add_recent_readings(db_conn, minutes_ago=2, temp=22.0):
    at = utc_timestamp(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    db_conn.executemany(
        "INSERT INTO sensor_readings VALUES (1, ?, ?, ?)",
        [(1, at, temp), (8, at, 55.0), (6, at, 30000.0)],
    )
    db_conn.commit()


# --- helpers ----------------------------------------------------------------

@pytest.mark.parametrize(
    "delta, text",
    [(timedelta(seconds=30), "just now"), (timedelta(minutes=4), "4 min ago"),
     (timedelta(hours=3), "3 h ago"), (timedelta(days=12), "12 days ago")],
)
def test_age_text(delta, text):
    assert age_text(utc_timestamp(NOW - delta), NOW) == text


def test_is_stale():
    assert not is_stale(utc_timestamp(NOW - timedelta(minutes=15)), NOW)
    assert is_stale(utc_timestamp(NOW - timedelta(minutes=16)), NOW)


def test_display_value():
    assert display_value("temperature", 20.0, "US") == 68.0
    assert display_value("temperature", 20.0, "SI") == 20.0
    assert display_value("humidity", 55.04, "US") == 55.0


def test_history_by_measure():
    history = DataFrame({
        "measure": ["humidity", "temperature", "temperature"],
        "reading_utc": ["2026-09-26 19:00:00", "2026-09-26 19:00:00", "2026-09-26 19:05:00"],
        "value": [50.0, 20.0, 21.0],
    })
    series = history_by_measure(history, "US", "America/Los_Angeles")
    assert list(series) == ["temperature", "humidity"]
    temp = series["temperature"]
    assert list(temp["value"]) == [68.0, 69.8]
    assert str(temp.index[0]) == "2026-09-26 12:00:00"  # PDT, naive for charting


# --- pages ------------------------------------------------------------------

def test_indoor_page_with_fresh_readings(seeded_db, db_conn):
    add_recent_readings(db_conn)
    at = run_page("views/indoor.py")
    assert not at.exception
    values = {m.label: m.value for m in at.metric}
    assert values == {"Temperature": "71.6 °F", "Humidity": "55.0 % (RH)", "Light (raw)": "30000.0"}
    assert not at.warning
    assert [s.value for s in at.subheader] == ["Temperature (°F)", "Humidity (% (RH))", "Light (raw)"]


def test_indoor_page_warns_when_stale(seeded_db):
    at = run_page("views/indoor.py")  # fixture readings are from 2025
    assert "Automation ignores readings older" in at.warning[0].value
    assert "No readings in the last 24 hours" in at.info[0].value


def test_indoor_page_without_readings(seeded_db, db_conn):
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.commit()
    at = run_page("views/indoor.py")
    assert not at.exception
    assert "No readings from the greenhouse yet" in at.info[0].value


def test_home_page_fresh_and_online(seeded_db, db_conn):
    add_recent_readings(db_conn)
    db_conn.execute("INSERT INTO device_status (device_id, status, updated_utc) VALUES (1, 'online', ?)", (utc_timestamp(),))
    db_conn.commit()
    at = run_page("views/home.py")
    assert not at.exception
    markdown = [m.value for m in at.markdown]
    # Status is shown with an icon and a word, never colour alone.
    assert ":green-badge[:material/check_circle: Online]" in markdown
    assert ":green-badge[:material/check_circle: Fresh]" in markdown
    assert ":material/toggle_on: **Fan**: On (web)" in markdown


def test_home_page_offline_and_stale(seeded_db, db_conn):
    db_conn.execute("INSERT INTO device_status (device_id, status, updated_utc) VALUES (1, 'offline', '2026-01-01 00:00:00')")
    db_conn.commit()
    markdown = [m.value for m in run_page("views/home.py").markdown]
    assert ":red-badge[:material/error: Offline]" in markdown
    assert ":orange-badge[:material/warning: Stale]" in markdown


def test_home_page_empty_database(seeded_db, db_conn):
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.execute("DELETE FROM relay_events")
    db_conn.commit()
    at = run_page("views/home.py")
    assert not at.exception
    markdown = " ".join(m.value for m in at.markdown)
    assert ":gray-badge[:material/help: Unknown]" in markdown
    assert "No status received yet." in markdown
    assert "No relay changes logged yet." in markdown
