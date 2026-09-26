"""Tests for server/core/timeutil.py and server/core/settings.py."""
from datetime import datetime, time, timedelta, timezone

import pytest

from core import settings, timeutil


def test_utc_timestamp_converts_aware_times():
    pacific = timezone(timedelta(hours=-7))
    assert timeutil.utc_timestamp(datetime(2026, 9, 26, 12, 0, 5, tzinfo=pacific)) == "2026-09-26 19:00:05"


def test_utc_timestamp_now_format():
    assert len(timeutil.utc_timestamp()) == 19


def test_parse_utc_timestamp_round_trip():
    moment = timeutil.parse_utc_timestamp("2025-10-27 16:15:00")
    assert moment.tzinfo == timezone.utc
    assert timeutil.utc_timestamp(moment) == "2025-10-27 16:15:00"


def test_from_open_meteo():
    assert timeutil.from_open_meteo("2025-10-27T16:15") == "2025-10-27 16:15:00"


@pytest.mark.parametrize("value", ["06:00", "06:00:00", time(6, 0)])
def test_format_time_of_day(value):
    assert timeutil.format_time_of_day(value) == "06:00"


def test_parse_time_of_day_rejects_garbage():
    with pytest.raises(ValueError):
        timeutil.parse_time_of_day("6 am")


@pytest.mark.parametrize("text, minutes", [("00:30", 30), ("01:15:00", 75), ("00:00", 0)])
def test_duration_to_minutes(text, minutes):
    assert timeutil.duration_to_minutes(text) == minutes


def test_relative_sqlite_url_resolves_against_server_dir():
    url = settings.resolve_db_url("sqlite:///data/greenhouse.db")
    assert url == "sqlite:///" + (settings.SERVER_DIR / "data" / "greenhouse.db").as_posix()


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "postgresql://host/db"])
def test_other_urls_unchanged(url):
    assert settings.resolve_db_url(url) == url
    assert settings.sqlite_path(url) is None
