"""Tests for server/core/migrations.py: fresh install and version 1 upgrade."""
import sqlite3

import pytest

from core import migrations
from support import TEST_DB_PATH, build_v1_db


@pytest.fixture
def db_file(tmp_path):
    return tmp_path / "greenhouse.db"


def query(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_fresh_install(db_file):
    assert "Created" in migrations.upgrade(db_file)
    assert query(db_file, "PRAGMA user_version") == [(2,)]
    assert query(db_file, "SELECT * FROM devices") == [(1, "picow1")]
    assert query(db_file, "SELECT count(*) FROM relays") == [(8,)]
    assert query(db_file, "SELECT count(*) FROM thresholds") == [(8,)]  # 4 x 2 profiles


def test_upgrade_is_idempotent(db_file):
    migrations.upgrade(db_file)
    assert "already" in migrations.upgrade(db_file)


def test_migrate_v1(db_file):
    build_v1_db(db_file)
    message = migrations.upgrade(db_file)
    assert "Migrated" in message and "'dropped_events': 1" in message

    assert query(db_file, "PRAGMA user_version") == [(2,)]
    assert not {"d_actions", "relay_status", "weather_data"} & {
        r[0] for r in query(db_file, "SELECT name FROM sqlite_master")
    }
    assert query(db_file, "SELECT * FROM devices ORDER BY 1") == [(1, "picow1"), (2, "picow2")]
    assert query(db_file, "SELECT relay_id, name FROM relays WHERE device_id = 1 AND relay_id <= 4") == [
        (1, "water"), (2, "fan"), (3, "heater"), (4, "light"),
    ]
    assert query(db_file, "SELECT * FROM sensor_readings ORDER BY reading_utc") == [
        (1, 1, "2025-10-20 23:10:53", 35.0),
        (1, 8, "2025-10-21 21:49:47", 55.0),
    ]
    assert query(db_file, "SELECT relay_id, event_utc, state, source FROM relay_events ORDER BY event_id") == [
        (2, "2025-10-04 20:25:10", 1, "web"),
        (2, "2025-10-04 20:30:00", 0, "auto"),
        (3, "2025-10-05 08:00:00", 1, "auto"),
    ]


def test_migrate_v1_settings_types(db_file):
    build_v1_db(db_file)
    migrations.upgrade(db_file)
    assert query(db_file, "SELECT name, relay_id, value, buffer FROM thresholds "
                          "WHERE profile = 'current' ORDER BY name") == [
        ("fan_on_humidity_pct", 2, 50.0, 2.0),
        ("fan_on_temp_c", 2, 32.0, 2.0),
        ("heater_on_temp_c", 3, 18.0, 2.0),
        ("light_on_level", 4, 3.0, 0.0),
    ]
    # Current slot 1 was saved as HH:MM:SS by the old settings page.
    assert query(db_file, "SELECT profile, slot, start_local, duration_min FROM watering_schedule "
                          "WHERE slot = 1 ORDER BY profile") == [
        ("current", 1, "07:15", 45),
        ("default", 1, "06:00", 30),
    ]


def test_migrate_v1_weather_types(db_file):
    build_v1_db(db_file)
    migrations.upgrade(db_file)
    assert query(db_file, "SELECT measured_utc, latitude, typeof(latitude), weather_code, "
                          "wind_direction_deg, sunrise_utc FROM weather_readings") == [
        ("2025-10-27 16:15:00", 39.533943, "real", 0, 338.0, "2025-10-27 14:22:00"),
    ]


def test_migrate_v1_writes_backup(db_file):
    build_v1_db(db_file)
    migrations.upgrade(db_file)
    (backup,) = db_file.parent.glob("greenhouse.v1-backup-*.db")
    assert query(backup, "SELECT count(*) FROM relay_status") == [(4,)]


def test_failed_migration_rolls_back(db_file, monkeypatch):
    build_v1_db(db_file)
    monkeypatch.setattr(migrations, "V1_THRESHOLD_NAMES", {"fan_on_temp": "not_a_threshold"})
    with pytest.raises(sqlite3.IntegrityError):
        migrations.upgrade(db_file)
    tables = {r[0] for r in query(db_file, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "relay_status" in tables and "relay_events" not in tables


def test_unknown_layout_is_refused(db_file):
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE something_else (x)")
    conn.close()
    with pytest.raises(RuntimeError, match="Unrecognised"):
        migrations.upgrade(db_file)


def test_upgrade_defaults_to_configured_database(seeded_db):
    assert str(TEST_DB_PATH.name) in migrations.upgrade()
