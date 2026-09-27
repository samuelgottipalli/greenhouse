"""
Tests for server/services/automation.py: loading inputs from the database,
acting on decisions, and the loop. The rules themselves are covered in
test_automation_rules.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from core import db
from services import automation

# Fixture readings are from 2025-10-22 22:38:12; "now" is 5 minutes later.
FRESH_NOW = datetime(2025, 10, 22, 22, 43, 12, tzinfo=timezone.utc)


@pytest.fixture
def sent(seeded_db, monkeypatch):
    commands = []
    monkeypatch.setattr(
        automation, "publish_relay_command",
        lambda **kw: commands.append((kw["relay_id"], kw["state"], kw["source"])) or True,
    )
    # No watering, whatever the time of day.
    db.save_settings({}, {slot: ("00:00", 0) for slot in (1, 2, 3, 4)})
    return commands


def add_reading(db_conn, measure_id, value, at="2025-10-22 22:40:00"):
    db_conn.execute("INSERT INTO sensor_readings VALUES (1, ?, ?, ?)", (measure_id, at, value))
    db_conn.commit()


def test_load_inputs(seeded_db):
    limits, slots, readings, states, relay_ids = automation.load_inputs()
    assert limits["fan_on_temp_c"] == (32.0, 2.0)
    assert slots[0] == ("06:00", 30)
    assert readings["temperature"].value == 21.5
    assert readings["temperature"].at == datetime(2025, 10, 22, 22, 38, 12, tzinfo=timezone.utc)
    assert states["fan"].state == 1 and states["fan"].source == "web"
    assert relay_ids["heater"] == 3


def test_old_readings_hold_fan_and_keep_heater_off(sent):
    # Fixture: fan on (web, 2025-10-27 01:00), heater off; readings are days
    # older than "now", so the fan is held and the heater stays off.
    now = datetime(2025, 10, 27, 3, 0, tzinfo=timezone.utc)
    assert automation.run_once(now=now) == []
    assert sent == []


def test_fan_off_when_cool_and_dry(sent, db_conn):
    add_reading(db_conn, 1, 20.0)
    add_reading(db_conn, 8, 40.0)
    now = datetime(2025, 10, 27, 1, 5, tzinfo=timezone.utc)
    db_conn.execute("UPDATE sensor_readings SET reading_utc = '2025-10-27 01:04:00' WHERE reading_utc = '2025-10-22 22:40:00'")
    db_conn.commit()
    # The fan was switched on from the web 5 minutes ago: manual override holds it.
    assert sent == [] and automation.run_once(now=now) == []
    later = now + timedelta(minutes=61)
    db_conn.execute("UPDATE sensor_readings SET reading_utc = '2025-10-27 02:05:00' WHERE reading_utc = '2025-10-27 01:04:00'")
    db_conn.commit()
    automation.run_once(now=later)
    assert sent == [(2, 0, "auto")]


def test_heater_command_goes_to_heater_relay(sent, db_conn):
    add_reading(db_conn, 1, 5.0)
    actions = automation.run_once(now=FRESH_NOW)
    assert (3, 1, "auto") in sent
    assert [a.relay for a in actions if a.state == 1] == ["heater"]
    latest = db.latest_relay_states().set_index("relay").loc["heater"]
    assert (latest["state"], latest["source"]) == (1, "auto")


def test_missing_settings_does_nothing(sent, db_conn):
    db_conn.execute("DELETE FROM thresholds")
    db_conn.commit()
    assert automation.run_once(now=FRESH_NOW) == []
    assert sent == []


def test_loop_sleeps_between_passes_and_survives_errors(seeded_db, monkeypatch):
    calls, pauses = [], []

    def flaky(now=None, device_id=1):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database locked")
        return []

    monkeypatch.setattr(automation, "run_once", flaky)
    automation.main(pause=pauses.append, max_passes=3)
    assert len(calls) == 3
    assert pauses == [automation.POLL_SECONDS] * 3  # formerly S-06 (4): no busy loop


def test_run_once_defaults_to_now(sent):
    # With the real clock the fixture readings are stale: only safe actions result.
    actions = automation.run_once()
    assert all(a.state == 0 or a.relay == "water" for a in actions)
    assert all(source == "auto" for _, _, source in sent)


def test_failed_publish_is_not_logged_and_retried(seeded_db, db_conn, monkeypatch):
    # S-19: automation logged commands the broker never accepted.
    db.save_settings({}, {slot: ("00:00", 0) for slot in (1, 2, 3, 4)})
    add_reading(db_conn, 1, 5.0)
    calls = []
    monkeypatch.setattr(automation, "publish_relay_command", lambda **kw: calls.append(kw) or False)
    assert automation.run_once(now=FRESH_NOW) == []
    assert db.latest_relay_states().set_index("relay").loc["heater", "state"] == 0
    automation.run_once(now=FRESH_NOW)
    assert len([c for c in calls if c["relay_id"] == 3]) == 2  # tried again next pass
