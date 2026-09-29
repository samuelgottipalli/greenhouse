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
    assert query(db_file, "PRAGMA user_version") == [(migrations.SCHEMA_VERSION,)]
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

    assert query(db_file, "PRAGMA user_version") == [(migrations.SCHEMA_VERSION,)]
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
        ("light_on_level", 4, 15000.0, 10000.0),  # old 3.0 replaced by the raw-level default
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


def test_fresh_clone_creates_missing_data_folder(tmp_path):
    # server/data/ is not in git, so a fresh clone may not have it (R-02).
    target = tmp_path / "data" / "greenhouse.db"
    assert "Created" in migrations.upgrade(target)
    assert query(target, "SELECT count(*) FROM watering_schedule") == [(8,)]


def make_v2(path):
    """Turn a fresh current database back into the version 2 layout."""
    migrations.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE device_status")
    conn.execute("DROP TABLE app_preferences")
    conn.execute("DROP TABLE service_heartbeats")
    conn.execute("DROP TABLE alerts")
    conn.execute("UPDATE measures SET name = 'light_intensity', si_unit = 'lm', us_unit = 'lm' WHERE measure_id = 6")
    conn.execute("INSERT INTO sensor_readings VALUES (1, 6, '2026-01-01 00:00:00', 30000)")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()


def test_upgrade_v2_to_v3(db_file):
    make_v2(db_file)
    assert f"from version 2 to {migrations.SCHEMA_VERSION}" in migrations.upgrade(db_file)
    assert query(db_file, "PRAGMA user_version") == [(migrations.SCHEMA_VERSION,)]
    assert query(db_file, "SELECT name, si_unit FROM measures WHERE measure_id = 6") == [("light_raw", "raw")]
    assert query(db_file, "SELECT count(*) FROM device_status") == [(0,)]
    assert query(db_file, "SELECT count(*) FROM app_preferences") == [(0,)]
    assert query(db_file, "SELECT value FROM sensor_readings WHERE measure_id = 6") == [(30000.0,)]


def test_v1_migration_renames_light_measure(db_file):
    build_v1_db(db_file)
    migrations.upgrade(db_file)
    assert query(db_file, "SELECT name FROM measures WHERE measure_id = 6") == [("light_raw",)]


def test_v2_upgrade_writes_backup(db_file):
    make_v2(db_file)
    migrations.upgrade(db_file)
    (backup,) = db_file.parent.glob("greenhouse.v2-backup-*.db")
    assert query(backup, "PRAGMA user_version") == [(2,)]


def test_future_version_is_refused(db_file):
    migrations.upgrade(db_file)
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RuntimeError, match="unsupported schema version 99"):
        migrations.upgrade(db_file)


def make_v3(path):
    """Turn a fresh current database back into the version 3 layout, with one status row."""
    migrations.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE service_heartbeats")
    conn.execute("DROP TABLE alerts")
    conn.execute("DROP TABLE device_status")
    conn.execute(migrations.V3_DDL[0])
    conn.execute("INSERT INTO device_status (device_id, status, updated_utc) VALUES (1, 'online', '2026-09-26 19:00:00')")
    conn.execute("PRAGMA user_version = 3")
    conn.commit()
    conn.close()


def test_upgrade_v3_to_v4_keeps_status(db_file):
    make_v3(db_file)
    assert f"from version 3 to {migrations.SCHEMA_VERSION}" in migrations.upgrade(db_file)
    assert query(db_file, "PRAGMA user_version") == [(migrations.SCHEMA_VERSION,)]
    assert query(db_file, "SELECT * FROM device_status") == [
        (1, "online", "2026-09-26 19:00:00") + (None,) * 9]
    assert query(db_file, "SELECT count(*) FROM service_heartbeats") == [(0,)]


def test_every_step_matches_fresh_schema(db_file, tmp_path):
    """A database upgraded step by step has the same tables and columns as a new one."""
    fresh = tmp_path / "fresh.db"
    migrations.upgrade(fresh)
    make_v2(db_file)
    migrations.upgrade(db_file)

    def layout(path):
        tables = [r[0] for r in query(path, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {t: [(c[1], c[2], c[3]) for c in query(path, f"PRAGMA table_info({t})")] for t in tables}

    assert layout(db_file) == layout(fresh)


FIRMWARE_COLUMNS = ("firmware_version", "firmware_name", "firmware_state", "firmware_detail", "firmware_utc")


def make_v6(path):
    """Turn a fresh current database back into the version 6 layout, with one reported build."""
    migrations.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE device_status DROP COLUMN firmware_name")
    conn.execute("INSERT INTO device_status (device_id, status, updated_utc, firmware_version, firmware_state) "
                 "VALUES (1, 'online', '2026-09-26 19:00:00', '3f9a0c1b2d4e', 'running')")
    conn.execute("PRAGMA user_version = 6")
    conn.commit()
    conn.close()


def test_upgrade_v6_to_v7_adds_the_version_name(db_file):
    make_v6(db_file)
    assert f"from version 6 to {migrations.SCHEMA_VERSION}" in migrations.upgrade(db_file)
    assert query(db_file, "SELECT firmware_version, firmware_name FROM device_status") == [("3f9a0c1b2d4e", None)]


def make_v5(path):
    """Turn a fresh current database back into the version 5 layout, with one status row."""
    migrations.upgrade(path)
    conn = sqlite3.connect(path)
    for column in FIRMWARE_COLUMNS:
        conn.execute(f"ALTER TABLE device_status DROP COLUMN {column}")
    conn.execute("INSERT INTO device_status (device_id, status, updated_utc, uptime_s) "
                 "VALUES (1, 'online', '2026-09-26 19:00:00', 60)")
    conn.execute("PRAGMA user_version = 5")
    conn.commit()
    conn.close()


def test_upgrade_v5_to_v6_adds_firmware_columns(db_file):
    make_v5(db_file)
    assert f"from version 5 to {migrations.SCHEMA_VERSION}" in migrations.upgrade(db_file)
    assert query(db_file, "SELECT uptime_s, firmware_version, firmware_state FROM device_status") == [(60, None, None)]
    conn = sqlite3.connect(db_file)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE device_status SET firmware_utc = 'yesterday'")
    conn.close()


def make_v4(path, light=(3.0, 0.0)):
    """Turn a fresh current database back into the version 4 layout."""
    migrations.upgrade(path)
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE alerts")
    for column in FIRMWARE_COLUMNS:
        conn.execute(f"ALTER TABLE device_status DROP COLUMN {column}")
    conn.execute("UPDATE thresholds SET value = ?, buffer = ? WHERE name = 'light_on_level' AND profile = 'current'", light)
    conn.execute("UPDATE thresholds SET value = 3.0, buffer = 0 WHERE name = 'light_on_level' AND profile = 'default'")
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()


def test_upgrade_v4_to_v5_fixes_old_light_default(db_file):
    make_v4(db_file)
    assert f"from version 4 to {migrations.SCHEMA_VERSION}" in migrations.upgrade(db_file)
    assert query(db_file, "SELECT profile, value, buffer FROM thresholds WHERE name = 'light_on_level' ORDER BY profile") == [
        ("current", 15000.0, 10000.0), ("default", 15000.0, 10000.0)]
    assert query(db_file, "SELECT count(*) FROM alerts") == [(0,)]


def test_upgrade_v4_to_v5_keeps_a_calibrated_light_level(db_file):
    make_v4(db_file, light=(22000.0, 8000.0))
    migrations.upgrade(db_file)
    assert query(db_file, "SELECT value, buffer FROM thresholds WHERE name = 'light_on_level' AND profile = 'current'") == [
        (22000.0, 8000.0)]


def test_backup_includes_changes_still_in_the_wal(db_file, tmp_path):
    migrations.upgrade(db_file)
    writer = sqlite3.connect(db_file)
    writer.execute("PRAGMA journal_mode = WAL")
    writer.execute("INSERT INTO sensor_readings VALUES (1, 1, '2030-01-01 00:00:00', 42.0)")
    writer.commit()  # committed, but still in greenhouse.db-wal
    target = tmp_path / "copy.db"
    migrations.backup_to(writer, target)
    writer.close()
    assert query(target, "SELECT value FROM sensor_readings") == [(42.0,)]


def test_backup_db_script(seeded_db, tmp_path, capsys):
    from scripts import backup_db

    target = tmp_path / "manual.db"
    assert backup_db.main([str(target)]) == 0
    assert query(target, "SELECT count(*) FROM relay_events") == query(seeded_db, "SELECT count(*) FROM relay_events")
    assert "Backed up" in capsys.readouterr().out


def test_upgrade_v7_to_v8_adds_monthly_stats(db_file):
    migrations.upgrade(db_file)
    conn = sqlite3.connect(db_file)
    conn.execute("DROP TABLE monthly_stats")
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()
    assert "from version 7 to 8" in migrations.upgrade(db_file)
    assert query(db_file, "SELECT count(*) FROM monthly_stats") == [(0,)]
    conn = sqlite3.connect(db_file)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO monthly_stats VALUES ('greenhouse', 1, 'temperature', '2026-9', 1, 1, 1, 1, 1, 1, "
                     "1, 1, 1, NULL, 'x')")
    conn.close()
