"""Tests for server/core/weather_api.py and services/weather_collector.py."""
from datetime import datetime, timedelta

import pytest

from core import db, settings, weather_api
from services import weather_collector

SAMPLE_RESPONSE = {
    "latitude": 39.533943,
    "longitude": -119.75715,
    "timezone": "GMT",
    "elevation": 1346.0,
    "current": {
        "time": "2025-10-27T16:15",
        "temperature": 7.0,
        "apparent_temperature": 4.7,
        "relative_humidity_2m": 63,
        "precipitation": 0.0,
        "rain": 0.0,
        "snowfall": 0.0,
        "showers": 0.0,
        "weather_code": 0,
        "wind_speed_10m": 1.9,
        "wind_direction_10m": 338,
    },
    "daily": {"sunrise": ["2025-10-27T14:22"], "sunset": ["2025-10-28T01:03"]},
}


def test_clean_data_flattens_response():
    row = weather_api.clean_data(SAMPLE_RESPONSE)
    assert row["measured_utc"] == "2025-10-27 16:15:00"
    assert row["sunrise_utc"] == "2025-10-27 14:22:00"
    assert row["sunset_utc"] == "2025-10-28 01:03:00"
    assert row["latitude"] == 39.533943
    assert row["relative_humidity_pct"] == 63
    assert len(row) == 16


@pytest.mark.parametrize("empty", [None, {}])
def test_clean_data_empty(empty):
    assert weather_api.clean_data(empty) is None


def test_cleaned_row_is_stored(seeded_db, db_conn):
    assert db.insert_weather(weather_api.clean_data(SAMPLE_RESPONSE)) is True
    row = db_conn.execute(
        "SELECT temperature_c, weather_code FROM weather_readings WHERE measured_utc = '2025-10-27 16:15:00'"
    ).fetchone()
    assert row == (7.0, 0)


def test_fetch_weather_missing_config():
    assert weather_api.fetch_weather() is None  # tests blank WEATHER_API


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_API", "https://example.test/?lat={LATITUDE}&lon={LONGITUDE}")
    monkeypatch.setattr(settings, "LATITUDE", "1.5")
    monkeypatch.setattr(settings, "LONGITUDE", "-2.5")


def test_fetch_weather_formats_url(configured, monkeypatch):
    calls = []

    class FakeResponse:
        def json(self):
            return SAMPLE_RESPONSE

        def raise_for_status(self):
            pass

    monkeypatch.setattr(weather_api, "get", lambda url, timeout: calls.append((url, timeout)) or FakeResponse())
    assert weather_api.fetch_weather() == SAMPLE_RESPONSE
    assert calls == [("https://example.test/?lat=1.5&lon=-2.5", 10)]


def test_fetch_weather_http_error(configured, monkeypatch):
    from requests import HTTPError

    class ServerError:
        def raise_for_status(self):
            raise HTTPError("503")

    monkeypatch.setattr(weather_api, "get", lambda url, timeout: ServerError())
    assert weather_api.fetch_weather() is None


def test_fetch_weather_network_error(configured, monkeypatch):
    def boom(url, timeout):
        raise ConnectionError("offline")

    monkeypatch.setattr(weather_api, "get", boom)
    assert weather_api.fetch_weather() is None


def test_collect_once_stores_a_row(seeded_db, monkeypatch):
    monkeypatch.setattr(weather_collector, "fetch_weather", lambda: SAMPLE_RESPONSE)
    assert weather_collector.collect_once() is True
    assert weather_collector.collect_once() is True  # the same slot again replaces it


def test_collect_once_without_data(seeded_db, monkeypatch):
    monkeypatch.setattr(weather_collector, "fetch_weather", lambda: None)
    assert weather_collector.collect_once() is False


# --- collector scheduling (S-13) --------------------------------------------


class FakeTime:
    def __init__(self, start):
        self.now = start
        self.sleeps = []

    def __call__(self):
        return self.now

    def pause(self, seconds):
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


@pytest.mark.parametrize(
    "moment, slot",
    [("10:00:00", "10:00"), ("10:14:59", "10:00"), ("10:15:00", "10:15"), ("10:59:30", "10:45")],
)
def test_slot_start(moment, slot):
    start = weather_collector.slot_start(datetime.fromisoformat(f"2026-09-26T{moment}.123"))
    assert start.strftime("%H:%M:%S.%f") == f"{slot}:00.000000"


def test_one_collection_per_slot(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_collector, "collect_once", lambda: calls.append(clock.now) or True)
    clock = FakeTime(datetime(2026, 9, 26, 10, 7, 3))
    weather_collector.run(now=clock, pause=clock.pause, max_passes=6 * 60)  # one hour of 10 s polls
    slots = [c.strftime("%H:%M") for c in calls]
    assert slots == ["10:07", "10:15", "10:30", "10:45", "11:00"]


def test_slow_pass_does_not_miss_a_slot(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_collector, "collect_once", lambda: calls.append(clock.now) or True)
    clock = FakeTime(datetime(2026, 9, 26, 10, 14, 55))
    real_pause = clock.pause
    clock.pause = lambda s: real_pause(s + 20)  # every sleep overruns by 20 s
    weather_collector.run(now=clock, pause=clock.pause, max_passes=3)
    assert [c.strftime("%H:%M") for c in calls] == ["10:14", "10:15"]


def test_failed_fetch_is_retried_once(monkeypatch):
    results = iter([False, True, False, False])
    monkeypatch.setattr(weather_collector, "collect_once", lambda: next(results))
    clock = FakeTime(datetime(2026, 9, 26, 10, 14, 50))
    weather_collector.run(now=clock, pause=clock.pause, max_passes=3)
    assert clock.sleeps[:2] == [30, 10]  # retry after 30 s, then normal polling
