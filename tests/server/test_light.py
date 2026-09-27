"""Tests for grow light automation (PLAN 4.7)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from core import db
from core.automation import LIGHT_MIN_SWITCH, Reading, RelayState, decide, is_daylight, light_target

LIMITS = {
    "fan_on_temp_c": (30.0, 2.0), "fan_on_humidity_pct": (70.0, 5.0),
    "heater_on_temp_c": (10.0, 2.0), "light_on_level": (15000.0, 10000.0),
}
NOW = datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc)  # noon in Los Angeles
LONG_AGO = timedelta(hours=3)


@pytest.mark.parametrize(
    "case, light, is_on, daylight, expected",
    [
        ("sunny day, off", 40000, False, True, False),
        ("cloudy day, off", 9000, False, True, True),
        ("cloudy day, lamp on, still dim", 20000, True, True, True),     # within buffer (lamp adds light)
        ("brightening, lamp on", 26000, True, True, False),              # above level + buffer
        ("exactly at level", 15000, False, True, False),
        ("night, lamp on", 9000, True, False, False),
        ("night, lamp off", 100, False, False, False),
        ("no weather data", 9000, False, None, None),
        ("day, no fresh reading", None, False, True, None),
    ],
)
def test_light_target(case, light, is_on, daylight, expected):
    assert light_target(LIMITS, light, is_on, daylight, LONG_AGO)[0] is expected, case


def test_no_flicker_within_min_switch_time():
    assert light_target(LIMITS, 9000, False, True, LIGHT_MIN_SWITCH - timedelta(seconds=1))[0] is None
    assert light_target(LIMITS, 9000, False, True, LIGHT_MIN_SWITCH)[0] is True


def test_sunset_switches_off_even_right_after_a_change():
    assert light_target(LIMITS, 9000, True, False, timedelta(minutes=1))[0] is False


def utc(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


def test_is_daylight_uses_any_recent_window():
    # Open-Meteo "today" is a UTC day: the LA afternoon of Oct 27 (00:30 UTC Oct 28)
    # lies in the window reported with Oct 27's data.
    windows = [(utc("2025-10-27 14:22"), utc("2025-10-28 01:03")), (utc("2025-10-28 14:23"), utc("2025-10-29 01:02"))]
    assert is_daylight(windows, utc("2025-10-28 00:30")) is True
    assert is_daylight(windows, utc("2025-10-28 05:00")) is False
    assert is_daylight([], utc("2025-10-28 05:00")) is None


def test_decide_includes_light_by_name():
    readings = {"temperature": Reading(20.0, NOW), "humidity": Reading(50.0, NOW), "light_raw": Reading(5000.0, NOW)}
    states = {n: RelayState(0, "auto", NOW - LONG_AGO) for n in ("fan", "heater", "water", "light")}
    actions = decide(LIMITS, [("06:00", 0)], readings, states, NOW, ZoneInfo("America/Los_Angeles"), daylight=True)
    assert [(a.relay, a.state) for a in actions] == [("light", 1)]
    assert decide(LIMITS, [("06:00", 0)], readings, states, NOW, ZoneInfo("America/Los_Angeles"), daylight=None) == []


def test_service_turns_light_on_when_dim_in_daytime(seeded_db, db_conn, monkeypatch):
    from services import automation

    db.save_settings({}, {slot: ("00:00", 0) for slot in (1, 2, 3, 4)})
    now = datetime.now(timezone.utc).replace(microsecond=0)
    at = now.strftime("%Y-%m-%d %H:%M:%S")
    db_conn.executemany("INSERT INTO sensor_readings VALUES (1, ?, ?, ?)",
                        [(1, at, 20.0), (8, at, 50.0), (6, at, 5000.0)])
    db_conn.execute("DELETE FROM weather_readings")
    db_conn.execute(
        "INSERT INTO weather_readings (measured_utc, latitude, longitude, sunrise_utc, sunset_utc) VALUES (?, 1, 2, ?, ?)",
        (at, (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"), (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")),
    )
    db_conn.commit()
    sent = []
    monkeypatch.setattr(automation, "publish_relay_command", lambda **kw: sent.append((kw["relay_id"], kw["state"])) or True)
    monkeypatch.setattr(automation, "publish_device_settings", lambda payload, device_id: True)
    automation.run_once(now=now)
    assert (4, 1) in sent


def test_daylight_unknown_without_weather(seeded_db, db_conn):
    from services import automation

    db_conn.execute("DELETE FROM weather_readings")
    db_conn.commit()
    assert automation.daylight_at(datetime.now(timezone.utc)) is None


def test_settings_page_saves_light_level(seeded_db):
    from streamlit.testing.v1 import AppTest
    from support import SERVER_DIR

    at = AppTest.from_file(str(SERVER_DIR / "views/greenhouse_settings.py"), default_timeout=30).run()
    assert at.number_input(key="light_on_level").value == 15000.0
    at.number_input(key="light_on_level").set_value(12000.0)
    at.number_input(key="light_on_level_buffer").set_value(8000.0)
    next(b for b in at.button if b.label == "Save").click().run()
    assert db.read_thresholds().set_index("name").loc["light_on_level", ["value", "buffer"]].tolist() == [12000.0, 8000.0]
