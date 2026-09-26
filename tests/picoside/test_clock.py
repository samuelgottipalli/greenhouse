"""Tests for picoside/device/clock.py: calendar maths, DST rules and the Clock class."""
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from pico_fakes import FakeNtp


@pytest.fixture
def clock(pico):
    return pico.clock


def test_days_from_civil_matches_datetime(clock):
    for day in range(-800, 30000, 7):
        d = date(1970, 1, 1) + timedelta(days=day)
        assert clock.days_from_civil(d.year, d.month, d.day) == day
        assert clock.civil_from_days(day) == (d.year, d.month, d.day)


def test_from_epoch_matches_datetime(clock):
    for seconds in (0, 951782400, 1772960400, 4102444799):
        expected = datetime.fromtimestamp(seconds, timezone.utc)
        assert clock.from_epoch(seconds) == expected.timetuple()[:6]
        assert clock.to_epoch(*expected.timetuple()[:6]) == seconds


def test_weekday_and_sundays(clock):
    assert clock.weekday(2026, 9, 26) == date(2026, 9, 26).weekday()
    assert clock.nth_sunday(2026, 3, 2) == 8
    assert clock.nth_sunday(2026, 11, 1) == 1
    assert clock.last_sunday(2026, 3) == 29
    assert clock.last_sunday(2026, 10) == 25
    assert clock.last_sunday(2026, 12) == 27


@pytest.mark.parametrize(
    "zone, std, rule",
    [
        ("America/Los_Angeles", -480, "us"),
        ("America/New_York", -300, "us"),
        ("Europe/London", 0, "eu"),
        ("Europe/Berlin", 60, "eu"),
        ("Asia/Tokyo", 540, "none"),
        ("America/Phoenix", -420, "none"),
    ],
)
@pytest.mark.parametrize("year", [2026, 2027])
def test_offset_matches_zoneinfo_every_hour(clock, zone, std, rule, year):
    tz = ZoneInfo(zone)
    start = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
    for hour in range(0, 366 * 24):
        moment = start + hour * 3600
        expected = datetime.fromtimestamp(moment, tz).utcoffset().total_seconds() // 60
        assert clock.utc_offset_minutes(moment, std, rule) == expected, (zone, hour)


def test_us_transition_instants(clock):
    # 2026: DST starts 2026-03-08 10:00 UTC, ends 2026-11-01 09:00 UTC (Pacific).
    start = clock.to_epoch(2026, 3, 8, 10)
    end = clock.to_epoch(2026, 11, 1, 9)
    assert not clock.is_dst(start - 1, -480, "us") and clock.is_dst(start, -480, "us")
    assert clock.is_dst(end - 1, -480, "us") and not clock.is_dst(end, -480, "us")


@pytest.mark.parametrize(
    "seconds, text",
    [(42, " 42s"), (900, "900s"), (901, " 15m"), (6 * 3600 + 1, "  6h"), (3 * 86400 + 1, "  3d"), (40 * 86400, " 40d")],
)
def test_format_uptime(clock, seconds, text):
    assert clock.format_uptime(seconds) == text


def make_clock(pico, utc_fields, **overrides):
    config = {"utc_offset_minutes": -480, "dst_rule": "us", "ntp_host": "pool.ntp.org", **overrides}
    ntp = FakeNtp()
    return pico.clock.Clock(config, ntp=ntp, gmtime=lambda: utc_fields), ntp


def test_unset_clock(pico):
    clk, _ = make_clock(pico, (2021, 1, 1, 0, 0, 5, 4, 1))
    assert not clk.is_set()
    assert clk.utc_str() is None and clk.local_str() is None


def test_utc_and_local_strings_summer(pico):
    clk, _ = make_clock(pico, (2026, 7, 4, 19, 30, 0, 5, 185))
    assert clk.utc_str() == "2026-07-04 19:30:00"
    assert clk.local_str() == "2026-07-04 12:30:00"  # PDT, UTC-7


def test_local_string_winter_crosses_midnight(pico):
    clk, _ = make_clock(pico, (2026, 1, 1, 3, 0, 0, 3, 1))
    assert clk.local_str() == "2025-12-31 19:00:00"  # PST, UTC-8


def test_sync_sets_host_and_flag(pico):
    clk, ntp = make_clock(pico, (2026, 1, 1, 0, 0, 0, 3, 1), ntp_host="time.example")
    assert clk.sync() is True and clk.synced
    assert ntp.host == "time.example" and ntp.calls == 1


def test_sync_failure_is_reported_not_raised(pico):
    clk, ntp = make_clock(pico, (2021, 1, 1, 0, 0, 0, 4, 1))
    ntp.ok = False
    assert clk.sync() is False and not clk.synced


def test_real_gmtime_default(pico):
    clk = pico.clock.Clock({"utc_offset_minutes": 0, "dst_rule": "none", "ntp_host": "x"}, ntp=FakeNtp())
    assert clk.is_set()
    assert abs(clk.utc_seconds() - time.time()) < 5
