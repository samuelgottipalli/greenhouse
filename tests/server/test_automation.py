"""
Tests for server/services/automation.py.

One pass of the loop is run by making ``sleep`` raise, with MQTT publishing
captured. These pin down the current behaviour of the port; the loop is
rewritten in PLAN step 1.1.
"""
from datetime import datetime

import pytest

from core import db
from services import automation


class StopLoop(Exception):
    pass


@pytest.fixture
def run_once(seeded_db, monkeypatch):
    """Run one loop pass and return the relay commands it published."""
    sent = []
    monkeypatch.setattr(
        automation, "publish_relay_command", lambda **kw: sent.append((kw["relay_id"], kw["state"]))
    )

    def stop(_seconds):
        raise StopLoop

    monkeypatch.setattr(automation, "sleep", stop)
    # No watering during the test, whatever the time of day.
    db.save_settings({}, {slot: ("00:00", 0) for slot in (1, 2, 3, 4)})

    def _run():
        with pytest.raises(StopLoop):
            automation.main()
        return sent

    return _run


def set_reading(db_conn, measure_id, value):
    db_conn.execute(
        "INSERT INTO sensor_readings VALUES (1, ?, '2030-01-01 00:00:00', ?)", (measure_id, value)
    )
    db_conn.commit()


def test_watering_windows():
    schedule = {"start_local": ["06:00", "23:50"], "duration_min": [30, 20]}
    now = datetime(2026, 9, 26, 6, 10)
    assert automation.watering_windows(schedule, now) == [
        (datetime(2026, 9, 26, 6, 0), datetime(2026, 9, 26, 6, 30)),
        (datetime(2026, 9, 26, 23, 50), datetime(2026, 9, 27, 0, 10)),
    ]


def test_fan_turns_off_when_cool_and_dry(run_once):
    # Fixture: fan on, 21.5 C / 45 % against triggers 32 C / 50 %.
    # S-06 (2): the humidity and temperature blocks each send "off".
    assert run_once() == [(2, 0), (2, 0)]
    assert db.latest_relay_states().set_index("relay_id").loc[2, "source"] == "auto"


def test_fan_turns_on_when_humid(run_once, db_conn):
    db.log_relay_event(relay_id=2, state=0, source="web", event_utc="2030-01-01 00:00:00")
    set_reading(db_conn, 8, 70.0)
    assert (2, 1) in run_once()


def test_nothing_happens_without_readings(run_once, db_conn, monkeypatch):
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.commit()
    calls = []
    # With data missing the loop never sleeps (S-06 4); stop it on the next read.
    real = automation.db.latest_sensor_readings

    def count_reads():
        calls.append(1)
        if len(calls) > 2:
            raise StopLoop
        return real()

    monkeypatch.setattr(automation.db, "latest_sensor_readings", count_reads)
    assert run_once() == []
    assert len(calls) == 3


@pytest.mark.known_bug
@pytest.mark.xfail(strict=True, reason="S-06 (1): heater commands are published to the fan relay")
def test_cold_turns_heater_on(run_once, db_conn):
    set_reading(db_conn, 1, 10.0)
    assert (3, 1) in run_once()
