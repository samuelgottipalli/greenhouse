"""Tests for server/core/weather_api.py and services/weather_collector.py."""
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

    monkeypatch.setattr(weather_api, "get", lambda url: calls.append(url) or FakeResponse())
    assert weather_api.fetch_weather() == SAMPLE_RESPONSE
    assert calls == ["https://example.test/?lat=1.5&lon=-2.5"]


def test_fetch_weather_network_error(configured, monkeypatch):
    def boom(url):
        raise ConnectionError("offline")

    monkeypatch.setattr(weather_api, "get", boom)
    assert weather_api.fetch_weather() is None


def test_collect_once_stores_a_row(seeded_db, monkeypatch):
    monkeypatch.setattr(weather_collector, "fetch_weather", lambda: SAMPLE_RESPONSE)
    assert weather_collector.collect_once() is True
    assert weather_collector.collect_once() is False  # duplicate time slot


def test_collect_once_without_data(seeded_db, monkeypatch):
    monkeypatch.setattr(weather_collector, "fetch_weather", lambda: None)
    assert weather_collector.collect_once() is False
