"""
Paths, environment and fixture data shared by the whole test suite.

``core.settings`` reads the environment when it is imported, and
``load_dotenv`` never overrides a variable that is already set, so importing
this module first isolates the tests from ``server/.env``: the database points
at a throwaway file and MQTT/weather settings are blanked. The ``seeded_db``
fixture (tests/conftest.py) builds a fresh database there.

Kept out of conftest.py so nested conftest files and test modules can import
it by a unique name.
"""
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_ROOT / "server"
PICO_DIR = REPO_ROOT / "picoside" / "device"
PICO_TOOLS_DIR = REPO_ROOT / "picoside"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
APP_DEFAULT_ZONE = "America/Los_Angeles"

_TEST_DB_DIR = Path(os.environ.get("PYTEST_GREENHOUSE_DB_DIR", REPO_ROOT / "tests" / ".tmp"))
_TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
TEST_DB_PATH = _TEST_DB_DIR / "test_greenhouse.db"

os.environ["DB_CONNECTION_STRING"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["TIMEZONE"] = APP_DEFAULT_ZONE
os.environ["DEVICE_ID"] = "1"
os.environ["MQTT_HOST"] = "localhost"
os.environ["MQTT_PORT"] = "1883"
os.environ["LATITUDE"] = "39.5349"  # the fixture's weather readings are for this place
os.environ["LONGITUDE"] = "-119.7527"
for _name in ("MQTT_USERNAME", "MQTT_PASSWORD", "WEATHER_API", "APP_PASSWORD_HASH",
              "NTFY_URL", "NTFY_TOKEN", "PUBLIC_HOST", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO"):
    os.environ[_name] = ""

if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def reset_db_file(path: Path) -> sqlite3.Connection:
    """
    Empty a database file in place and return an autocommit connection to it.

    Tables are dropped rather than the file deleted: the app's cached engine
    may hold pooled connections, which lock the file on Windows.

    Args:
        path (Path): Database file.

    Returns:
        sqlite3.Connection: Connection with foreign keys off (so drops succeed).
    """
    conn = sqlite3.connect(path, isolation_level=None)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for table in tables:
        conn.execute(f'DROP TABLE "{table}"')
    conn.execute("PRAGMA user_version = 0")
    return conn


def build_db(
    path: Path = TEST_DB_PATH,
    weather_rows: int = 4,
    weather_days_ago: int = 0,
    wind_direction: float = 200,
) -> None:
    """
    Create a version 2 database with reference data and sample readings.

    Relay events: fan last switched on from the web, heater last switched off
    by automation, water and light off from the web.

    Args:
        path (Path): Database file to (re)create.
        weather_rows (int): Number of 15-minute weather readings to insert,
            ending at local noon.
        weather_days_ago (int): Put the readings this many days in the past;
            1 simulates a collector that stopped yesterday.
        wind_direction (float): Wind direction in degrees for every reading.
    """
    from core import migrations

    conn = reset_db_file(path)
    conn.execute("PRAGMA foreign_keys = ON")
    migrations.create_new(conn)
    conn.executemany(
        "INSERT INTO sensor_readings VALUES (?, ?, ?, ?)",
        [
            (1, 1, "2025-10-22 22:38:12", 21.5),
            (1, 8, "2025-10-22 22:38:12", 45.0),
            (1, 1, "2025-10-21 22:38:12", 19.0),
        ],
    )
    conn.executemany(
        "INSERT INTO relay_events (device_id, relay_id, event_utc, state, source) VALUES (?, ?, ?, ?, ?)",
        [
            (1, 2, "2025-10-26 01:00:00", 0, "web"),
            (1, 1, "2025-10-27 01:00:00", 0, "web"),
            (1, 2, "2025-10-27 01:00:00", 1, "web"),
            (1, 3, "2025-10-27 01:00:00", 0, "auto"),
            (1, 4, "2025-10-27 01:00:00", 0, "web"),
        ],
    )
    # The weather page shows rows whose date, in the app's default zone
    # (America/Los_Angeles), is today there. Anchor readings at local noon and
    # store them in UTC, as the collector does.
    local_noon = datetime.now(ZoneInfo(APP_DEFAULT_ZONE)).replace(hour=12, minute=0, second=0, microsecond=0)
    noon_utc = (local_noon - timedelta(days=weather_days_ago)).astimezone(timezone.utc)
    for i in range(weather_rows):
        ts = noon_utc - timedelta(minutes=15 * i)
        conn.execute(
            "INSERT INTO weather_readings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ts.strftime("%Y-%m-%d %H:%M:%S"), 39.53, -119.75, 1346.0,
                10.0 + i, 8.0 + i, 50.0 + i, 0.2, 0.2, 0.0, 0.0, 3, 5.0, wind_direction,
                noon_utc.strftime("%Y-%m-%d 06:00:00"),
                noon_utc.strftime("%Y-%m-%d 18:00:00"),
            ),
        )
    conn.close()


# Version 1 fixture: reference rows copied from the production database (Oct 2025).
V1_ACTIONS = [
    ("000", "Error"), ("010", "Auto-Off"), ("011", "Auto-On"),
    ("020", "Manual-Off-From-Webapp"), ("021", "Manual-On-From-Webapp"),
    ("030", "Manual-Off-From-Device"), ("031", "Manual-On-From-Device"),
    ("999", "Unknown"),
]
V1_DEVICES = [("001", "picow1"), ("002", "picow2")]
V1_MEASURES = [
    ("001", "temperature", "°C", "°F"), ("002", "speed", "kmph", "mph"),
    ("003", "distance_long", "km", "mi"), ("004", "distance_short", "cm", "in"),
    ("005", "distance_medium", "m", "ft"), ("006", "light_intensity", "lm", "lm"),
    ("007", "pressure", "hPa", "inHg"), ("008", "humidity", "% (RH)", "% (RH)"),
    ("009", "direction", "°", "°"),
]
V1_RELAYS = [("1", "water"), ("2", "fan"), ("3", "heater"), ("4", "light")]
V1_CONDITIONS = [
    ("001", "4", "1", "3.0", None, "light_on_lumen"),
    ("001", "2", "1", "32", "2", "fan_on_temp"),
    ("001", "1", "1", "06:00", "00:30", "water_on_time_1"),
    ("001", "3", "1", "18", "2", "heater_on_temp"),
    ("001", "1", "4", "00:00", "00:00", "water_on_time_4"),
    ("001", "1", "3", "00:00", "00:00", "water_on_time_3"),
    ("001", "1", "2", "00:00", "00:00", "water_on_time_2"),
    ("001", "2", "2", "50", "2", "fan_on_humidity"),
]


def build_v1_db(path: Path) -> None:
    """
    Create a database in the original (version 1) layout with sample data.

    Includes the quirks found in production: ``value_002`` holding ``''``,
    text IDs, and a settings row saved as ``HH:MM:SS`` (bug S-02).

    Args:
        path (Path): Database file to (re)create.
    """
    conn = reset_db_file(path)
    conn.executescript((FIXTURES_DIR / "schema_v1.sql").read_text(encoding="utf-8"))
    conn.executemany("INSERT INTO d_actions VALUES (?, ?)", V1_ACTIONS)
    conn.executemany("INSERT INTO d_devices VALUES (?, ?)", V1_DEVICES)
    conn.executemany("INSERT INTO d_measures VALUES (?, ?, ?, ?)", V1_MEASURES)
    conn.executemany("INSERT INTO d_relays VALUES (?, ?)", V1_RELAYS)
    conn.executemany("INSERT INTO relay_conditions_default VALUES (?, ?, ?, ?, ?, ?)", V1_CONDITIONS)
    current = [row if row[5] != "water_on_time_1" else ("001", "1", "1", "07:15:00", "00:45:00", row[5])
               for row in V1_CONDITIONS]
    conn.executemany("INSERT INTO relay_conditions VALUES (?, ?, ?, ?, ?, ?)", current)
    conn.executemany(
        "INSERT INTO greenhouse_data VALUES (?, ?, ?, ?, ?)",
        [
            ("2025-10-20 23:10:53", "001", "001", 35, 0),
            ("2025-10-21 21:49:47", "001", "008", 55, ""),
        ],
    )
    conn.executemany(
        "INSERT INTO relay_status VALUES (?, ?, ?, ?)",
        [
            ("2025-10-04 20:25:10", "001", "2", "021"),
            ("2025-10-04 20:30:00", "001", "2", "010"),
            ("2025-10-05 08:00:00", "001", "3", "011"),
            ("2025-10-05 09:00:00", "001", "1", "999"),
        ],
    )
    conn.execute(
        "INSERT INTO weather_data VALUES ('39.533943', '-119.75715', 'GMT', '2025-10-27 16:15:00', "
        "1346, 7, 4.7, 63, 0, 0, 0, 0, 0, 1.9, 338, '2025-10-27 14:22:00', '2025-10-28 01:03:00')"
    )
    conn.close()



def section_app(name: str, device_id: int | None = None):
    """
    An AppTest (not yet run) that draws one tab's section (``server/sections/<name>.py``)
    the way its tabbed page does, after the usual page setup.

    Args:
        name (str): Section module, e.g. ``"greenhouse"``.
        device_id (int | None): Controller to select first.
    """
    from streamlit.testing.v1 import AppTest

    script = (f"import ui\nui.page_setup('Test', 'wide')\n"
              f"from sections import {name}\n{name}.render()\n")
    at = AppTest.from_string(script, default_timeout=30)
    if device_id:
        at.session_state["device_id"] = device_id
    return at


def run_section(name: str, device_id: int | None = None):
    """Run :func:`section_app` and return the result."""
    return section_app(name, device_id).run()
