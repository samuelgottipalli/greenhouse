"""
Clock for the greenhouse controller: NTP sync, local time and uptime text.

The RTC always holds UTC (set by NTP). Local time is worked out only for
display, from ``utc_offset_minutes`` and a daylight-saving rule in
``config.json`` (written by ``picoside/setup_config.py``):

* ``"none"``: no daylight saving.
* ``"us"``: +1 h from 02:00 local on the 2nd Sunday of March to 02:00 local
  on the 1st Sunday of November.
* ``"eu"``: +1 h from 01:00 UTC on the last Sunday of March to 01:00 UTC on
  the last Sunday of October.

Date arithmetic is done here rather than with ``time.mktime`` so it behaves
the same on MicroPython (whatever its epoch) and on CPython (for tests).
"""
import time

MIN_VALID_YEAR = 2024
DST_RULES = ("none", "us", "eu")


def days_from_civil(year, month, day):
    """
    Count days from 1970-01-01 to a date (proleptic Gregorian calendar).

    Args:
        year (int): Year.
        month (int): Month, 1-12.
        day (int): Day of month.

    Returns:
        int: Days since 1970-01-01 (negative before it).
    """
    year -= 1 if month <= 2 else 0
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(days):
    """
    Inverse of :func:`days_from_civil`.

    Args:
        days (int): Days since 1970-01-01.

    Returns:
        tuple: ``(year, month, day)``.
    """
    days += 719468
    era = (days if days >= 0 else days - 146096) // 146097
    doe = days - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + (3 if mp < 10 else -9)
    return (yoe + era * 400 + (1 if month <= 2 else 0), month, day)


def to_epoch(year, month, day, hour=0, minute=0, second=0):
    """
    Convert date and time fields to seconds since 1970-01-01.

    Returns:
        int: Seconds since 1970-01-01 00:00:00.
    """
    return days_from_civil(year, month, day) * 86400 + hour * 3600 + minute * 60 + second


def from_epoch(seconds):
    """
    Convert seconds since 1970-01-01 to date and time fields.

    Args:
        seconds (int): Seconds since 1970-01-01 00:00:00.

    Returns:
        tuple: ``(year, month, day, hour, minute, second)``.
    """
    days, rest = divmod(int(seconds), 86400)
    hour, rest = divmod(rest, 3600)
    minute, second = divmod(rest, 60)
    return civil_from_days(days) + (hour, minute, second)


def weekday(year, month, day):
    """
    Return the day of the week.

    Returns:
        int: 0 = Monday ... 6 = Sunday.
    """
    return (days_from_civil(year, month, day) + 3) % 7


def nth_sunday(year, month, n):
    """
    Return the day of month of the n-th Sunday.

    Args:
        year (int): Year.
        month (int): Month, 1-12.
        n (int): 1 for the first Sunday, 2 for the second, ...

    Returns:
        int: Day of month.
    """
    return 1 + (6 - weekday(year, month, 1)) % 7 + 7 * (n - 1)


def last_sunday(year, month):
    """
    Return the day of month of the last Sunday.

    Returns:
        int: Day of month.
    """
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    last_day = days_from_civil(next_year, next_month, 1) - days_from_civil(year, month, 1)
    return last_day - (weekday(year, month, last_day) + 1) % 7


def is_dst(utc_seconds, std_offset_minutes, rule):
    """
    Tell whether daylight saving time is in effect.

    Args:
        utc_seconds (int): Moment, as seconds since 1970-01-01 UTC.
        std_offset_minutes (int): Standard (winter) offset from UTC, e.g. -480.
        rule (str): ``"none"``, ``"us"`` or ``"eu"``.

    Returns:
        bool: True during daylight saving time.
    """
    year = from_epoch(utc_seconds)[0]
    if rule == "us":
        start = to_epoch(year, 3, nth_sunday(year, 3, 2), 2) - std_offset_minutes * 60
        end = to_epoch(year, 11, nth_sunday(year, 11, 1), 2) - (std_offset_minutes + 60) * 60
        return start <= utc_seconds < end
    if rule == "eu":
        start = to_epoch(year, 3, last_sunday(year, 3), 1)
        end = to_epoch(year, 10, last_sunday(year, 10), 1)
        return start <= utc_seconds < end
    return False


def utc_offset_minutes(utc_seconds, std_offset_minutes, rule):
    """
    Return the offset from UTC in effect at a moment.

    Args:
        utc_seconds (int): Moment, as seconds since 1970-01-01 UTC.
        std_offset_minutes (int): Standard offset from UTC.
        rule (str): Daylight-saving rule (see module docstring).

    Returns:
        int: Offset in minutes (standard, or standard + 60 during DST).
    """
    return std_offset_minutes + (60 if is_dst(utc_seconds, std_offset_minutes, rule) else 0)


def format_timestamp(fields):
    """
    Format date and time fields as ``YYYY-MM-DD HH:MM:SS``.

    Args:
        fields (tuple): At least ``(year, month, day, hour, minute, second)``.

    Returns:
        str: Formatted timestamp (19 characters).
    """
    return "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*fields[:6])


def format_uptime(seconds):
    """
    Format an uptime compactly for the LCD.

    Seconds up to 15 minutes, then minutes up to 6 hours, then hours up to
    3 days, then days.

    Args:
        seconds (float): Uptime in seconds.

    Returns:
        str: Four characters, e.g. ``" 42s"``, ``" 17m"``, ``"  9h"``, ``" 12d"``.
    """
    if seconds > 3 * 24 * 3600:
        return "{:3d}d".format(int(seconds // 86400))
    if seconds > 6 * 3600:
        return "{:3d}h".format(int(seconds // 3600))
    if seconds > 15 * 60:
        return "{:3d}m".format(int(seconds // 60))
    return "{:3d}s".format(int(seconds))


class Clock:
    """
    Keeps the RTC in UTC via NTP and provides UTC and local timestamps.

    Attributes:
        std_offset (int): Standard offset from UTC in minutes.
        rule (str): Daylight-saving rule.
        synced (bool): True once an NTP sync has succeeded since boot.
    """

    def __init__(self, config, ntp=None, gmtime=None):
        """
        Args:
            config (dict): Parsed config; uses ``utc_offset_minutes``,
                ``dst_rule`` and ``ntp_host``.
            ntp (module | None): ``ntptime`` module (injected in tests).
            gmtime (callable | None): Returns the current UTC time tuple
                (injected in tests); defaults to ``time.gmtime``.
        """
        if ntp is None:
            import ntptime as ntp
        self._ntp = ntp
        self._gmtime = gmtime or time.gmtime
        self.std_offset = config["utc_offset_minutes"]
        self.rule = config["dst_rule"]
        self.host = config["ntp_host"]
        self.synced = False

    def sync(self):
        """
        Set the RTC to UTC from the NTP server.

        Returns:
            bool: True on success. Failures are printed, not raised.
        """
        try:
            self._ntp.host = self.host
            self._ntp.settime()
        except (OSError, OverflowError, IndexError) as err:
            print("NTP sync failed:", err)
            return False
        self.synced = True
        return True

    def is_set(self):
        """
        Tell whether the RTC holds a plausible date (it resets to 2021 on boot).

        Returns:
            bool: True if the year is 2024 or later.
        """
        return self._gmtime()[0] >= MIN_VALID_YEAR

    def utc_seconds(self):
        """
        Return the current time as seconds since 1970-01-01 UTC.

        Returns:
            int: Seconds.
        """
        return to_epoch(*self._gmtime()[:6])

    def utc_str(self):
        """
        Return the current UTC time for messages to the server.

        Returns:
            str | None: ``YYYY-MM-DD HH:MM:SS``, or None if the clock is not set.
        """
        return format_timestamp(self._gmtime()) if self.is_set() else None

    def local_minutes(self):
        """
        Return the local time of day in minutes (for watering slots).

        Returns:
            int | None: Minutes since local midnight, or None if the clock is
            not set.
        """
        if not self.is_set():
            return None
        now = self.utc_seconds()
        fields = from_epoch(now + utc_offset_minutes(now, self.std_offset, self.rule) * 60)
        return fields[3] * 60 + fields[4]

    def local_str(self):
        """
        Return the current local time for the LCD.

        Returns:
            str | None: ``YYYY-MM-DD HH:MM:SS`` local time, or None if the
            clock is not set.
        """
        if not self.is_set():
            return None
        now = self.utc_seconds()
        return format_timestamp(from_epoch(now + utc_offset_minutes(now, self.std_offset, self.rule) * 60))
