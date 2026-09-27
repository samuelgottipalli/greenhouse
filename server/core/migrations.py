"""
Create or upgrade the greenhouse SQLite database.

* An empty or missing database gets ``schema.sql`` plus the reference data in
  this module (one device, its relays, measures and default settings).
* A version 1 database (the original ``d_*`` / ``relay_conditions`` /
  ``weather_data`` tables) is backed up next to itself and converted to the
  current version in one transaction, keeping all data.
* Later versions are upgraded one step at a time (each step has its own
  frozen SQL, so it never depends on the current ``schema.sql``):

  * 2 -> 3: ``device_status`` and ``app_preferences`` tables; light measure
    renamed to ``light_raw`` (the LDR reports raw ADC counts, not lumens).
  * 3 -> 4: ``service_heartbeats`` table; device health columns
    (``last_seen_utc``, ``uptime_s``, ``mem_free``, ``rssi_dbm``).
  * 4 -> 5: ``alerts`` table; the light trigger default becomes a raw light
    level (the old 3.0 dates from when it was thought to be lumens).
* A current database is left alone.

Run it with ``python -m scripts.upgrade_db`` from the ``server/`` folder.
"""
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from core import settings
from core.timeutil import duration_to_minutes, format_time_of_day

log = logging.getLogger(__name__)

SCHEMA_VERSION: int = 5
SCHEMA_FILE: Path = Path(__file__).with_name("schema.sql")
MIN_SQLITE: tuple[int, int, int] = (3, 37, 0)  # STRICT tables

RELAY_NAMES: dict[int, str] = {
    1: "water", 2: "fan", 3: "heater", 4: "light",
    5: "spare_5", 6: "spare_6", 7: "spare_7", 8: "spare_8",
}
MEASURES: list[tuple[int, str, str, str]] = [
    (1, "temperature", "°C", "°F"),
    (2, "speed", "kmph", "mph"),
    (3, "distance_long", "km", "mi"),
    (4, "distance_short", "cm", "in"),
    (5, "distance_medium", "m", "ft"),
    (6, "light_raw", "raw", "raw"),
    (7, "pressure", "hPa", "inHg"),
    (8, "humidity", "% (RH)", "% (RH)"),
    (9, "direction", "°", "°"),
]
# Grow light: on below this raw LDR level (0-65535, brighter = higher) in daytime,
# off again above level + buffer. See RUNBOOK "Calibrating the light sensor".
LIGHT_ON_LEVEL: float = 15000.0
LIGHT_BUFFER: float = 10000.0
# (name, relay_id, value, buffer)
DEFAULT_THRESHOLDS: list[tuple[str, int, float, float]] = [
    ("fan_on_temp_c", 2, 32.0, 2.0),
    ("fan_on_humidity_pct", 2, 50.0, 2.0),
    ("heater_on_temp_c", 3, 18.0, 2.0),
    ("light_on_level", 4, LIGHT_ON_LEVEL, LIGHT_BUFFER),
]
# (slot, relay_id, start_local, duration_min)
DEFAULT_SCHEDULE: list[tuple[int, int, str, int]] = [
    (1, 1, "06:00", 30),
    (2, 1, "00:00", 0),
    (3, 1, "00:00", 0),
    (4, 1, "00:00", 0),
]
# Version 1 names -> version 2 threshold names.
V1_THRESHOLD_NAMES: dict[str, str] = {
    "fan_on_temp": "fan_on_temp_c",
    "fan_on_humidity": "fan_on_humidity_pct",
    "heater_on_temp": "heater_on_temp_c",
    "light_on_lumen": "light_on_level",
}
V1_SOURCES: dict[str, str] = {"1": "auto", "2": "web", "3": "device"}


def check_sqlite_version() -> None:
    """
    Fail early if SQLite is too old for STRICT tables.

    Raises:
        RuntimeError: If the linked SQLite library is older than 3.37.
    """
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise RuntimeError(
            f"SQLite {sqlite3.sqlite_version} is too old; version 3.37 or newer is required."
        )


def connect(path: Path) -> sqlite3.Connection:
    """
    Open a connection in autocommit mode with foreign keys enforced.

    Transactions are managed explicitly with BEGIN/COMMIT.

    Args:
        path (Path): Database file.

    Returns:
        sqlite3.Connection: Open connection.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def schema_statements() -> list[str]:
    """
    Split ``schema.sql`` into individual statements.

    Returns:
        list[str]: Complete SQL statements, in file order.
    """
    statements, current = [], ""
    for line in SCHEMA_FILE.read_text(encoding="utf-8").splitlines(keepends=True):
        if not current and line.lstrip().startswith("--"):
            continue
        current += line
        if sqlite3.complete_statement(current):
            statements.append(current.strip())
            current = ""
    return statements


def table_names(conn: sqlite3.Connection) -> set[str]:
    """
    Return the names of all tables in the database.

    Args:
        conn (sqlite3.Connection): Open connection.

    Returns:
        set[str]: Table names.
    """
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def detect_version(conn: sqlite3.Connection) -> int:
    """
    Work out which schema version a database has.

    Args:
        conn (sqlite3.Connection): Open connection.

    Returns:
        int: 0 for an empty database, 1 for the original schema, or the
        ``user_version`` stamped by ``schema.sql`` (2 or later).

    Raises:
        RuntimeError: If the tables match no known version.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version:
        return version
    tables = table_names(conn)
    if not tables:
        return 0
    if {"d_actions", "relay_status", "relay_conditions"} <= tables:
        return 1
    raise RuntimeError(f"Unrecognised database layout: {sorted(tables)}")


def create_schema(conn: sqlite3.Connection) -> None:
    """
    Create all version 2 tables. Must run inside a transaction.

    Args:
        conn (sqlite3.Connection): Open connection.
    """
    for statement in schema_statements():
        conn.execute(statement)


def seed_device(conn: sqlite3.Connection, device_id: int, name: str) -> None:
    """
    Add a device with relays 1-8 and default settings in both profiles.

    Args:
        conn (sqlite3.Connection): Open connection.
        device_id (int): New device ID.
        name (str): Device name, e.g. ``"picow1"``.
    """
    conn.execute("INSERT INTO devices VALUES (?, ?)", (device_id, name))
    conn.executemany(
        "INSERT INTO relays VALUES (?, ?, ?)",
        [(device_id, relay_id, relay) for relay_id, relay in RELAY_NAMES.items()],
    )
    for profile in ("default", "current"):
        conn.executemany(
            "INSERT INTO thresholds VALUES (?, ?, ?, ?, ?, ?)",
            [(device_id, profile, *row) for row in DEFAULT_THRESHOLDS],
        )
        conn.executemany(
            "INSERT INTO watering_schedule VALUES (?, ?, ?, ?, ?, ?)",
            [(device_id, profile, *row) for row in DEFAULT_SCHEDULE],
        )


def create_new(conn: sqlite3.Connection) -> None:
    """
    Build a fresh version 2 database with reference data for device 1.

    Args:
        conn (sqlite3.Connection): Connection to an empty database.
    """
    conn.execute("BEGIN")
    try:
        create_schema(conn)
        conn.executemany("INSERT INTO measures VALUES (?, ?, ?, ?)", MEASURES)
        seed_device(conn, settings.DEVICE_ID, "picow1")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _v1_settings_rows(conn: sqlite3.Connection, table: str, profile: str):
    """
    Convert version 1 ``relay_conditions`` rows to typed version 2 rows.

    Args:
        conn (sqlite3.Connection): Connection to the version 1 database.
        table (str): ``relay_conditions`` or ``relay_conditions_default``.
        profile (str): ``current`` or ``default``.

    Returns:
        tuple[list[tuple], list[tuple]]: Rows for ``thresholds`` and for
        ``watering_schedule``.
    """
    thresholds, schedule = [], []
    rows = conn.execute(f"SELECT deviceid, relayid, value, buffer, conditionname FROM {table}")
    for device_id, relay_id, value, buffer, name in rows:
        device_id, relay_id = int(device_id), int(relay_id)
        if name in V1_THRESHOLD_NAMES:
            thresholds.append((
                device_id, profile, V1_THRESHOLD_NAMES[name], relay_id,
                float(value), float(buffer) if buffer not in (None, "") else 0.0,
            ))
        elif name.startswith("water_on_time_"):
            schedule.append((
                device_id, profile, int(name.rsplit("_", 1)[1]), relay_id,
                format_time_of_day(value), duration_to_minutes(buffer),
            ))
        else:
            log.warning("Dropping unknown condition %r from %s", name, table)
    return thresholds, schedule


def migrate_v1(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Convert a version 1 database to version 2 in place, in one transaction.

    Relay actions are split into ``state`` (last digit of the old action ID)
    and ``source`` (middle digit: 1 auto, 2 web, 3 device). Rows with other
    action codes ("000" error, "999" unknown) are dropped and counted.

    Args:
        conn (sqlite3.Connection): Connection to a version 1 database.

    Returns:
        dict[str, int]: Rows written per new table, plus ``dropped_events``.
    """
    conn.execute("BEGIN")
    try:
        create_schema(conn)
        conn.execute(
            "INSERT INTO devices SELECT CAST(deviceid AS INTEGER), devicename FROM d_devices"
        )
        conn.execute(
            "INSERT INTO measures SELECT CAST(measureid AS INTEGER), measurename, "
            "COALESCE(siunit, ''), COALESCE(englishunit, '') FROM d_measures"
        )
        rename_light_measure(conn)
        v1_relays = {int(r): n for r, n in conn.execute("SELECT relayid, relayname FROM d_relays")}
        for (device_id,) in conn.execute("SELECT device_id FROM devices").fetchall():
            conn.executemany(
                "INSERT INTO relays VALUES (?, ?, ?)",
                [(device_id, rid, v1_relays.get(rid, name)) for rid, name in RELAY_NAMES.items()],
            )
        conn.execute(
            "INSERT INTO sensor_readings "
            "SELECT CAST(deviceid AS INTEGER), CAST(measureid AS INTEGER), measuredatetime, "
            "CAST(value_001 AS REAL) FROM greenhouse_data"
        )
        conn.execute(
            "INSERT INTO relay_events (device_id, relay_id, event_utc, state, source) "
            "SELECT CAST(deviceid AS INTEGER), CAST(relayid AS INTEGER), actiontime, "
            "CAST(substr(actionid, 3, 1) AS INTEGER), "
            "CASE substr(actionid, 2, 1) WHEN '1' THEN 'auto' WHEN '2' THEN 'web' ELSE 'device' END "
            "FROM relay_status WHERE actionid IN ('010', '011', '020', '021', '030', '031') "
            "ORDER BY actiontime"
        )
        for table, profile in (("relay_conditions", "current"), ("relay_conditions_default", "default")):
            thresholds, schedule = _v1_settings_rows(conn, table, profile)
            conn.executemany("INSERT INTO thresholds VALUES (?, ?, ?, ?, ?, ?)", thresholds)
            conn.executemany("INSERT INTO watering_schedule VALUES (?, ?, ?, ?, ?, ?)", schedule)
        fix_light_default(conn)
        conn.execute(
            "INSERT INTO weather_readings SELECT MEASURE_DATE, CAST(LATITUDE AS REAL), "
            "CAST(LONGITUDE AS REAL), ELEVATION, TEMPERATURE, APPARENT_TEMPERATURE, "
            "RELATIVE_HUMIDITY, PRECIPITATION, RAIN, SHOWERS, SNOWFALL, "
            "CAST(WEATHER_CODE AS INTEGER), WIND_SPEED, WIND_DIRECTION, SUNRISE_TIME, SUNSET_TIME "
            "FROM weather_data"
        )
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("devices", "relays", "measures", "sensor_readings", "relay_events",
                          "thresholds", "watering_schedule", "weather_readings")
        }
        counts["dropped_events"] = (
            conn.execute("SELECT count(*) FROM relay_status").fetchone()[0] - counts["relay_events"]
        )
        for table in ("relay_status", "greenhouse_data", "relay_conditions",
                      "relay_conditions_default", "weather_data", "d_relays", "d_actions",
                      "d_measures", "d_devices"):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("VACUUM")
    return counts


TIMESTAMP_CHECK = "GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'"

# Frozen DDL for each upgrade step (never edit after release).
V3_DDL: tuple[str, ...] = (
    "CREATE TABLE device_status (device_id INTEGER PRIMARY KEY REFERENCES devices (device_id) "
    "ON DELETE CASCADE, status TEXT NOT NULL CHECK (status IN ('online', 'offline')), "
    f"updated_utc TEXT NOT NULL CHECK (updated_utc {TIMESTAMP_CHECK})) STRICT",
    "CREATE TABLE app_preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT",
)
V4_DDL: tuple[str, ...] = (
    "ALTER TABLE device_status ADD COLUMN last_seen_utc TEXT",
    "ALTER TABLE device_status ADD COLUMN uptime_s INTEGER",
    "ALTER TABLE device_status ADD COLUMN mem_free INTEGER",
    "ALTER TABLE device_status ADD COLUMN rssi_dbm INTEGER",
    "CREATE TABLE service_heartbeats (service TEXT PRIMARY KEY, "
    f"updated_utc TEXT NOT NULL CHECK (updated_utc {TIMESTAMP_CHECK}), "
    "healthy INTEGER NOT NULL DEFAULT 1 CHECK (healthy IN (0, 1)), detail TEXT NOT NULL DEFAULT '') STRICT",
)


def rename_light_measure(conn: sqlite3.Connection) -> None:
    """
    Give measure 6 an honest name and unit: the LDR reports raw ADC counts.

    Args:
        conn (sqlite3.Connection): Open connection, inside a transaction.
    """
    conn.execute(
        "UPDATE measures SET name = 'light_raw', si_unit = 'raw', us_unit = 'raw' "
        "WHERE name = 'light_intensity'"
    )


def _step(conn: sqlite3.Connection, statements: tuple[str, ...], to_version: int, extra=None) -> None:
    """
    Apply one upgrade step in a single transaction.

    Args:
        conn (sqlite3.Connection): Open connection.
        statements (tuple[str, ...]): Frozen DDL for the step.
        to_version (int): Version stamped when it succeeds.
        extra (callable | None): Data changes to run in the same transaction.
    """
    conn.execute("BEGIN")
    try:
        for statement in statements:
            conn.execute(statement)
        if extra:
            extra(conn)
        conn.execute(f"PRAGMA user_version = {to_version}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def migrate_v2(conn: sqlite3.Connection) -> None:
    """
    Upgrade version 2 to 3: status and preferences tables, light measure renamed.

    Args:
        conn (sqlite3.Connection): Connection to a version 2 database.
    """
    _step(conn, V3_DDL, 3, rename_light_measure)


def migrate_v3(conn: sqlite3.Connection) -> None:
    """
    Upgrade version 3 to 4: service heartbeats and device health columns.

    Args:
        conn (sqlite3.Connection): Connection to a version 3 database.
    """
    _step(conn, V4_DDL, 4)


V5_DDL: tuple[str, ...] = (
    "CREATE TABLE alerts (alert_key TEXT PRIMARY KEY, active INTEGER NOT NULL CHECK (active IN (0, 1)), "
    f"message TEXT NOT NULL, since_utc TEXT NOT NULL CHECK (since_utc {TIMESTAMP_CHECK}), "
    f"last_sent_utc TEXT CHECK (last_sent_utc IS NULL OR last_sent_utc {TIMESTAMP_CHECK})) STRICT",
)


def fix_light_default(conn: sqlite3.Connection) -> None:
    """Replace the meaningless old light trigger (3.0) with the raw-level default."""
    conn.execute(
        "UPDATE thresholds SET value = ?, buffer = ? WHERE name = 'light_on_level' AND value = 3.0",
        (LIGHT_ON_LEVEL, LIGHT_BUFFER),
    )


def migrate_v4(conn: sqlite3.Connection) -> None:
    """
    Upgrade version 4 to 5: alerts table and a real light trigger default.

    Args:
        conn (sqlite3.Connection): Connection to a version 4 database.
    """
    _step(conn, V5_DDL, 5, fix_light_default)


STEPS = {2: migrate_v2, 3: migrate_v3, 4: migrate_v4}


def backup_to(conn: sqlite3.Connection, target: Path) -> None:
    """
    Copy a live database to a file with SQLite's backup API.

    Unlike a plain file copy this includes changes still in the WAL file and
    is consistent even while other processes are writing.

    Args:
        conn (sqlite3.Connection): Open connection to the database to copy.
        target (Path): Backup file to create.
    """
    destination = sqlite3.connect(target)
    try:
        conn.backup(destination)
    finally:
        destination.close()


def upgrade(path: Path | None = None) -> str:
    """
    Bring a database file to the current schema version.

    Args:
        path (Path | None): Database file. Defaults to the file named by
            ``DB_CONNECTION_STRING``.

    Returns:
        str: A one-line description of what was done.

    Raises:
        RuntimeError: If SQLite is too old, the URL is not a SQLite file, or
            the database layout is not recognised.
    """
    check_sqlite_version()
    path = path or settings.sqlite_path(settings.DB_URL)
    if path is None:
        raise RuntimeError("upgrade() only supports SQLite database files")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        version = detect_version(conn)
        if version == SCHEMA_VERSION:
            return f"{path} is already at schema version {SCHEMA_VERSION}"
        if version == 0:
            create_new(conn)
            return f"Created {path} at schema version {SCHEMA_VERSION}"
        if version != 1 and version not in STEPS:
            raise RuntimeError(f"{path} has unsupported schema version {version}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.stem}.v{version}-backup-{stamp}{path.suffix}")
        backup_to(conn, backup)
        if version == 1:
            counts = migrate_v1(conn)
            return f"Migrated {path} from version 1 (backup: {backup.name}): {counts}"
        start = version
        while version < SCHEMA_VERSION:
            STEPS[version](conn)
            version += 1
        return f"Upgraded {path} from version {start} to {SCHEMA_VERSION} (backup: {backup.name})"
    finally:
        conn.close()
