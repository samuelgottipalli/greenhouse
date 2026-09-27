"""
Time zones offered on the controller's setup page.

The controller can't hold the full time-zone database, so each entry stores
the standard UTC offset (minutes) and the daylight-saving rule from
``clock.DST_RULES``. Only zones the device reproduces exactly are listed;
``tests/picoside/test_provision.py`` checks every entry against Python's
``zoneinfo``. Other places can pick a fixed UTC offset instead
(:func:`fixed_offsets`), without daylight saving.
"""

ZONES = (
    ("America/Anchorage", -540, "us"),
    ("America/Los_Angeles", -480, "us"),
    ("America/Phoenix", -420, "none"),
    ("America/Denver", -420, "us"),
    ("America/Chicago", -360, "us"),
    ("America/New_York", -300, "us"),
    ("America/Halifax", -240, "us"),
    ("America/St_Johns", -210, "us"),
    ("Pacific/Honolulu", -600, "none"),
    ("America/Toronto", -300, "us"),
    ("America/Winnipeg", -360, "us"),
    ("America/Regina", -360, "none"),
    ("America/Mexico_City", -360, "none"),
    ("America/Bogota", -300, "none"),
    ("America/Lima", -300, "none"),
    ("America/Caracas", -240, "none"),
    ("America/Sao_Paulo", -180, "none"),
    ("America/Argentina/Buenos_Aires", -180, "none"),
    ("America/Puerto_Rico", -240, "none"),
    ("Atlantic/Reykjavik", 0, "none"),
    ("Europe/London", 0, "eu"),
    ("Europe/Dublin", 0, "eu"),
    ("Europe/Lisbon", 0, "eu"),
    ("Europe/Paris", 60, "eu"),
    ("Europe/Berlin", 60, "eu"),
    ("Europe/Madrid", 60, "eu"),
    ("Europe/Rome", 60, "eu"),
    ("Europe/Amsterdam", 60, "eu"),
    ("Europe/Brussels", 60, "eu"),
    ("Europe/Zurich", 60, "eu"),
    ("Europe/Vienna", 60, "eu"),
    ("Europe/Stockholm", 60, "eu"),
    ("Europe/Oslo", 60, "eu"),
    ("Europe/Copenhagen", 60, "eu"),
    ("Europe/Warsaw", 60, "eu"),
    ("Europe/Prague", 60, "eu"),
    ("Europe/Budapest", 60, "eu"),
    ("Europe/Athens", 120, "eu"),
    ("Europe/Helsinki", 120, "eu"),
    ("Europe/Bucharest", 120, "eu"),
    ("Europe/Kyiv", 120, "eu"),
    ("Europe/Istanbul", 180, "none"),
    ("Europe/Moscow", 180, "none"),
    ("Africa/Lagos", 60, "none"),
    ("Africa/Johannesburg", 120, "none"),
    ("Africa/Nairobi", 180, "none"),
    ("Asia/Dubai", 240, "none"),
    ("Asia/Karachi", 300, "none"),
    ("Asia/Kolkata", 330, "none"),
    ("Asia/Kathmandu", 345, "none"),
    ("Asia/Dhaka", 360, "none"),
    ("Asia/Bangkok", 420, "none"),
    ("Asia/Jakarta", 420, "none"),
    ("Asia/Singapore", 480, "none"),
    ("Asia/Manila", 480, "none"),
    ("Asia/Hong_Kong", 480, "none"),
    ("Asia/Shanghai", 480, "none"),
    ("Asia/Taipei", 480, "none"),
    ("Asia/Seoul", 540, "none"),
    ("Asia/Tokyo", 540, "none"),
    ("Australia/Perth", 480, "none"),
    ("Australia/Brisbane", 600, "none"),
    ("Australia/Darwin", 570, "none"),
    ("UTC", 0, "none"),
)


def find(name):
    """
    Look up a zone by its IANA name or a fixed-offset name.

    Args:
        name (str): e.g. ``"Europe/Paris"`` or ``"UTC+05:30"``.

    Returns:
        tuple | None: ``(name, utc_offset_minutes, dst_rule)``, or None if unknown.
    """
    for zone in ZONES:
        if zone[0] == name:
            return zone
    for zone in fixed_offsets():
        if zone[0] == name:
            return zone
    return None


def offset_name(minutes):
    """
    Name a fixed UTC offset.

    Args:
        minutes (int): Offset from UTC, e.g. 330.

    Returns:
        str: e.g. ``"UTC+05:30"``.
    """
    sign = "-" if minutes < 0 else "+"
    minutes = abs(minutes)
    return "UTC{}{:02d}:{:02d}".format(sign, minutes // 60, minutes % 60)


def fixed_offsets():
    """
    Whole- and half-hour offsets from UTC-12 to UTC+14, without daylight saving.

    Returns:
        list[tuple]: ``(name, utc_offset_minutes, "none")`` entries.
    """
    return [(offset_name(m), m, "none") for m in range(-12 * 60, 14 * 60 + 1, 30)]
