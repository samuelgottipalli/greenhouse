"""
Server configuration, loaded once from ``server/.env``.

Every module reads settings from here instead of calling ``load_dotenv`` and
``getenv`` itself. Variables already set in the process environment win over
``.env`` (``load_dotenv`` never overrides), which is how tests point the app at
a throwaway database.

A relative SQLite path in ``DB_CONNECTION_STRING`` is resolved against the
``server/`` folder, so the app and services work from any working directory.
"""
from os import getenv
from pathlib import Path

from dotenv import load_dotenv

SERVER_DIR: Path = Path(__file__).resolve().parent.parent
ENV_FILE: Path = SERVER_DIR / ".env"
DEFAULT_DB_URL: str = "sqlite:///data/greenhouse.db"

load_dotenv(dotenv_path=ENV_FILE)


def resolve_db_url(url: str) -> str:
    """
    Make a relative SQLite URL absolute, relative to ``server/``.

    Args:
        url (str): SQLAlchemy URL, e.g. ``sqlite:///data/greenhouse.db``.

    Returns:
        str: The URL with an absolute file path; non-SQLite and in-memory URLs
        are returned unchanged.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url == prefix + ":memory:":
        return url
    path = Path(url[len(prefix):])
    if not path.is_absolute():
        path = SERVER_DIR / path
    return prefix + path.as_posix()


def sqlite_path(url: str) -> Path | None:
    """
    Return the database file of a SQLite URL.

    Args:
        url (str): SQLAlchemy URL.

    Returns:
        Path | None: File path, or None if the URL is not a file-based SQLite URL.
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix) or url == prefix + ":memory:":
        return None
    return Path(resolve_db_url(url)[len(prefix):])


DB_URL: str = resolve_db_url(getenv("DB_CONNECTION_STRING", DEFAULT_DB_URL))

# Device served by the single-device UI and services (see d_devices / devices).
DEVICE_ID: int = int(getenv("DEVICE_ID", "1"))

# IANA zone used for the watering schedule and as the default display zone.
TIMEZONE: str = getenv("TIMEZONE", "UTC")

MQTT_HOST: str = getenv("MQTT_HOST", "localhost").strip()
MQTT_PORT: int = int(getenv("MQTT_PORT", "1883"))
MQTT_USERNAME: str | None = (getenv("MQTT_USERNAME") or "").strip() or None
MQTT_PASSWORD: str | None = (getenv("MQTT_PASSWORD") or "").strip() or None
MQTT_TOPIC_PREFIX: str = getenv("MQTT_TOPIC_PREFIX", "greenhouse")

# Address controllers use to reach this computer (broker and firmware updates);
# blank = MQTT_HOST if it names another machine, else the detected LAN address.
PUBLIC_HOST: str = (getenv("PUBLIC_HOST") or "").strip()

# Port of services/firmware_server.py (controller code for over-the-air updates).
FIRMWARE_PORT: int = int(getenv("FIRMWARE_PORT") or "8081")

# Dashboard login: hash from `python -m scripts.set_password`; empty = no login.
APP_PASSWORD_HASH: str | None = (getenv("APP_PASSWORD_HASH") or "").strip() or None

# Alerts (core/alerts.py) and where to send them (core/notify.py).
ALERT_TEMP_LOW_C: float = float(getenv("ALERT_TEMP_LOW_C", "5"))
ALERT_TEMP_HIGH_C: float = float(getenv("ALERT_TEMP_HIGH_C", "40"))
ALERT_COOLDOWN_MIN: int = int(getenv("ALERT_COOLDOWN_MIN", "60"))
NTFY_URL: str | None = (getenv("NTFY_URL") or "").strip() or None
NTFY_TOKEN: str | None = (getenv("NTFY_TOKEN") or "").strip() or None
SMTP_HOST: str | None = (getenv("SMTP_HOST") or "").strip() or None
SMTP_PORT: int = int(getenv("SMTP_PORT") or "587")
SMTP_USER: str | None = (getenv("SMTP_USER") or "").strip() or None
SMTP_PASSWORD: str | None = getenv("SMTP_PASSWORD") or None
ALERT_EMAIL_FROM: str | None = (getenv("ALERT_EMAIL_FROM") or "").strip() or None
ALERT_EMAIL_TO: str | None = (getenv("ALERT_EMAIL_TO") or "").strip() or None

WEATHER_API: str | None = getenv("WEATHER_API")
LATITUDE: str | None = getenv("LATITUDE")
LONGITUDE: str | None = getenv("LONGITUDE")
