"""
Date and time formats used in storage and on the wire.

Rules (see core/schema.sql):

* Timestamps are UTC text ``YYYY-MM-DD HH:MM:SS`` in columns ending ``_utc``.
  This is SQLite's native format, sorts correctly as text, and parses with
  ``pandas.to_datetime``.
* Times of day in schedules are local (``settings.TIMEZONE``) text ``HH:MM``.
* Durations are whole minutes (INTEGER).
"""
from datetime import datetime, time, timezone

TIMESTAMP_FORMAT: str = "%Y-%m-%d %H:%M:%S"
TIME_OF_DAY_FORMAT: str = "%H:%M"


def utc_timestamp(moment: datetime | None = None) -> str:
    """
    Format a moment as a storage timestamp.

    Args:
        moment (datetime | None): Aware datetime (any zone), or naive UTC.
            Defaults to now.

    Returns:
        str: UTC time as ``YYYY-MM-DD HH:MM:SS``.
    """
    if moment is None:
        moment = datetime.now(timezone.utc)
    elif moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime(TIMESTAMP_FORMAT)


def parse_utc_timestamp(text: str) -> datetime:
    """
    Parse a storage timestamp.

    Args:
        text (str): ``YYYY-MM-DD HH:MM:SS``.

    Returns:
        datetime: Aware datetime in UTC.
    """
    return datetime.strptime(text, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


def from_open_meteo(text: str) -> str:
    """
    Convert an Open-Meteo time (``YYYY-MM-DDTHH:MM``, UTC) to storage format.

    Args:
        text (str): Time as returned by the API when no ``timezone`` is requested.

    Returns:
        str: ``YYYY-MM-DD HH:MM:SS``.
    """
    return utc_timestamp(datetime.strptime(text, "%Y-%m-%dT%H:%M"))


def format_time_of_day(value: time | str) -> str:
    """
    Normalise a time of day to ``HH:MM``.

    Args:
        value (time | str): A ``datetime.time`` or a string ``HH:MM`` or
            ``HH:MM:SS``.

    Returns:
        str: ``HH:MM``.

    Raises:
        ValueError: If the string is not a valid time.
    """
    if isinstance(value, str):
        value = parse_time_of_day(value)
    return value.strftime(TIME_OF_DAY_FORMAT)


def parse_time_of_day(text: str) -> time:
    """
    Parse ``HH:MM`` (or legacy ``HH:MM:SS``) into a ``datetime.time``.

    Args:
        text (str): Time of day.

    Returns:
        time: Parsed time (seconds, if any, are kept).

    Raises:
        ValueError: If the string is not a valid time.
    """
    for fmt in (TIME_OF_DAY_FORMAT, "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Not a time of day: {text!r}")


def duration_to_minutes(text: str) -> int:
    """
    Convert a legacy ``HH:MM`` / ``HH:MM:SS`` duration string to minutes.

    Args:
        text (str): Duration, e.g. ``"00:30"`` or ``"01:15:00"``.

    Returns:
        int: Whole minutes (seconds are dropped).
    """
    parts = [int(p) for p in text.split(":")]
    return parts[0] * 60 + parts[1]
