"""Tests for server/core/db.py against the fixture database."""
import sqlite3

import pytest

from core import db, settings


def test_uses_test_database(seeded_db):
    assert settings.DB_URL.endswith(seeded_db.as_posix())


def test_engine_is_shared():
    assert db.get_engine() is db.get_engine()


def test_foreign_keys_enforced(seeded_db):
    # Relay 9 does not exist, so the event is rejected rather than stored.
    assert db.log_relay_event(relay_id=9, state=1, source="web") is False


def test_unit_labels(seeded_db):
    assert db.unit_labels("SI")["speed"] == "kmph"
    assert db.unit_labels("US")["temperature"] == "°F"


def test_relay_names(seeded_db):
    names = db.relay_names()
    assert names[1] == "water" and names[2] == "fan" and names[8] == "spare_8"


def test_read_thresholds(seeded_db):
    data = db.read_thresholds().set_index("name")
    assert data.loc["fan_on_temp_c", "value"] == 32.0
    assert data.loc["fan_on_temp_c", "relay_id"] == 2
    assert len(data) == 4


def test_read_watering_schedule(seeded_db):
    data = db.read_watering_schedule()
    assert list(data["slot"]) == [1, 2, 3, 4]
    assert data.iloc[0][["start_local", "duration_min"]].tolist() == ["06:00", 30]


def test_read_unknown_device_returns_none(seeded_db):
    assert db.read_thresholds(device_id=99) is None


def test_save_settings_updates_only_given_rows(seeded_db, db_conn):
    assert db.save_settings({"fan_on_temp_c": (30.5, 1.5)}, {2: ("18:30", 15)}) is True
    rows = dict(db_conn.execute(
        "SELECT name, value FROM thresholds WHERE profile = 'current'"
    ).fetchall())
    assert rows["fan_on_temp_c"] == 30.5
    assert rows["light_on_level"] == 3.0  # untouched
    slot = db_conn.execute(
        "SELECT start_local, duration_min FROM watering_schedule WHERE profile = 'current' AND slot = 2"
    ).fetchone()
    assert slot == ("18:30", 15)
    default = db_conn.execute(
        "SELECT value FROM thresholds WHERE profile = 'default' AND name = 'fan_on_temp_c'"
    ).fetchone()
    assert default == (32.0,)


@pytest.mark.parametrize(
    "thresholds, schedule",
    [
        ({"no_such_threshold": (1, 1)}, {}),
        ({}, {7: ("06:00", 10)}),        # no slot 7
        ({}, {1: ("6 am", 10)}),         # rejected by the HH:MM check
        ({"fan_on_temp_c": (30, -1)}, {}),  # negative buffer
    ],
)
def test_save_settings_rejects_bad_input_atomically(seeded_db, db_conn, thresholds, schedule):
    before = db_conn.execute("SELECT * FROM thresholds ORDER BY 1, 2, 3").fetchall()
    thresholds = {"heater_on_temp_c": (10.0, 1.0), **thresholds}
    assert db.save_settings(thresholds, schedule) is False
    assert db_conn.execute("SELECT * FROM thresholds ORDER BY 1, 2, 3").fetchall() == before


def test_restore_defaults(seeded_db, db_conn):
    db.save_settings({"fan_on_temp_c": (99.0, 9.0)}, {1: ("09:00", 5)})
    assert db.restore_default_settings() is True
    assert db_conn.execute(
        "SELECT value, buffer FROM thresholds WHERE profile = 'current' AND name = 'fan_on_temp_c'"
    ).fetchone() == (32.0, 2.0)
    assert db_conn.execute(
        "SELECT start_local, duration_min FROM watering_schedule WHERE profile = 'current' AND slot = 1"
    ).fetchone() == ("06:00", 30)


def test_latest_sensor_readings(seeded_db):
    data = db.latest_sensor_readings().set_index("measure")
    assert data.loc["temperature", "value"] == 21.5
    assert data.loc["temperature", "reading_utc"] == "2025-10-22 22:38:12"
    assert set(data.index) == {"temperature", "humidity"}


def test_latest_relay_states(seeded_db):
    data = db.latest_relay_states().set_index("relay_id")
    assert len(data) == 4
    assert data.loc[2, "state"] == 1 and data.loc[2, "source"] == "web"
    assert data.loc[3, "relay"] == "heater"


def test_log_relay_event_becomes_latest(seeded_db):
    assert db.log_relay_event(relay_id=2, state=0, source="auto", event_utc="2030-01-01 00:00:00")
    fan = db.latest_relay_states().set_index("relay_id").loc[2]
    assert (fan["state"], fan["source"]) == (0, "auto")


def test_same_second_events_keep_insert_order(seeded_db):
    for state in (1, 0, 1):
        db.log_relay_event(relay_id=4, state=state, source="web", event_utc="2030-01-01 00:00:00")
    assert db.latest_relay_states().set_index("relay_id").loc[4, "state"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"relay_id": 2, "state": 2, "source": "web"},
        {"relay_id": 2, "state": 1, "source": "someone"},
        {"relay_id": 2, "state": 1, "source": "web", "event_utc": "2030-01-01T00:00:00Z"},
    ],
)
def test_log_relay_event_rejects_bad_values(seeded_db, kwargs):
    assert db.log_relay_event(**kwargs) is False


def test_strict_tables_reject_wrong_types(seeded_db, db_conn):
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute("INSERT INTO sensor_readings VALUES (1, 1, '2030-01-01 00:00:00', 'warm')")


def test_recent_weather_newest_first(seeded_db):
    data = db.recent_weather(limit=2)
    assert len(data) == 2
    assert data.iloc[0]["measured_utc"] > data.iloc[1]["measured_utc"]


def test_insert_weather_rejects_empty_and_duplicates(seeded_db):
    row = db.recent_weather(limit=1).iloc[0].to_dict()
    assert db.insert_weather(None) is False
    assert db.insert_weather(row) is False  # same measured_utc already stored


def test_sensor_history_raw_and_hourly(seeded_db, db_conn):
    db_conn.executemany(
        "INSERT INTO sensor_readings VALUES (1, 1, ?, ?)",
        [("2030-01-01 10:05:00", 20.0), ("2030-01-01 10:35:00", 22.0), ("2030-01-01 11:10:00", 30.0)],
    )
    db_conn.commit()
    raw = db.sensor_history("2030-01-01 00:00:00")
    assert list(raw["value"]) == [20.0, 22.0, 30.0]
    hourly = db.sensor_history("2030-01-01 00:00:00", bucket="hour")
    assert hourly[["reading_utc", "value"]].values.tolist() == [
        ["2030-01-01 10:00:00", 21.0],
        ["2030-01-01 11:00:00", 30.0],
    ]
    assert db.sensor_history("2031-01-01 00:00:00") is None
    with pytest.raises(ValueError):
        db.sensor_history("2030-01-01 00:00:00", bucket="minute")


def test_latest_sensor_readings_picks_newest_per_measure(seeded_db, db_conn):
    db_conn.executemany(
        "INSERT INTO sensor_readings VALUES (1, ?, ?, ?)",
        [(1, "2030-01-01 00:00:00", 5.0), (1, "2029-01-01 00:00:00", 9.0), (6, "2030-02-01 00:00:00", 100.0)],
    )
    db_conn.commit()
    latest = db.latest_sensor_readings().set_index("measure")
    assert latest.loc["temperature", "value"] == 5.0
    assert latest.loc["light_raw", "reading_utc"] == "2030-02-01 00:00:00"
    assert latest.loc["humidity", "value"] == 45.0
