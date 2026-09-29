"""
Tests for the greenhouse's location (core/places.py, Settings › Location):
looking places up, storing the choice, and the weather collector and grow-light
daylight check following a change while everything runs.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from core import db, places, settings, weather_api
from support import run_section

GEOCODE = {"results": [
    {"name": "Sparks", "admin1": "Nevada", "country": "United States", "latitude": 39.53491,
     "longitude": -119.75269, "timezone": "America/Los_Angeles"},
    {"name": "Sparks", "admin1": "Oklahoma", "country": "United States", "latitude": 35.61, "longitude": -96.82,
     "timezone": "America/Chicago"},
    {"name": "Broken", "latitude": "not a number"},
]}


def test_search():
    urls = []
    found = places.search("Sparks", fetch=lambda url: urls.append(url) or json.dumps(GEOCODE).encode())
    assert "name=Sparks" in urls[0] and urls[0].startswith(places.GEOCODE_URL)
    assert found == [
        {"name": "Sparks, Nevada, United States", "latitude": 39.5349, "longitude": -119.7527,
         "timezone": "America/Los_Angeles"},
        {"name": "Sparks, Oklahoma, United States", "latitude": 35.61, "longitude": -96.82,
         "timezone": "America/Chicago"},
    ]


def test_search_offline_or_empty():
    def offline(url):
        raise OSError("no network")

    quiet = FakeGeocoder()  # never the real OpenStreetMap service in tests
    assert places.search("Sparks", fetch=offline, geocoder=quiet) == []
    assert places.search("Nowhere", fetch=lambda url: b"{}", geocoder=quiet) == []
    assert places.search("  ", fetch=lambda url: pytest.fail("no request for an empty name")) == []


def test_current_prefers_the_dashboard_choice(seeded_db):
    assert places.current()["source"] == "settings"  # tests set LATITUDE/LONGITUDE (support.py)
    places.save({"name": "Denver, Colorado, United States", "latitude": 39.7392, "longitude": -104.9847,
                 "timezone": "America/Denver"})
    now = places.current()
    assert (now["name"], now["latitude"], now["timezone"], now["source"]) == \
        ("Denver, Colorado, United States", 39.7392, "America/Denver", "dashboard")


def test_current_without_any_location(monkeypatch):
    monkeypatch.setattr(settings, "LATITUDE", "")
    assert places.current({}) is None


@pytest.mark.parametrize("lat, lon, ok", [(0, 0, True), (90, 180, True), (91, 0, False), ("x", 1, False),
                                          (None, 1, False)])
def test_valid(lat, lon, ok):
    assert places.valid(lat, lon) is ok


def test_save_rejects_a_bad_position(seeded_db):
    with pytest.raises(ValueError):
        places.save({"name": "Nowhere", "latitude": 200, "longitude": 0})


def test_near():
    sparks = {"latitude": 39.5349, "longitude": -119.7527}
    assert places.near(39.53, -119.75, sparks)  # Open-Meteo's grid point
    assert not places.near(39.74, -104.98, sparks)
    assert places.near(1, 2, None)


def test_fetch_follows_a_change_without_restarting(seeded_db, monkeypatch):
    """The collector asks for the location on every fetch, so a change applies to the next reading."""
    monkeypatch.setattr(settings, "WEATHER_API", "https://example.test/?lat={LATITUDE}&lon={LONGITUDE}")
    urls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {}

    monkeypatch.setattr(weather_api, "get", lambda url, timeout: urls.append(url) or Response())
    weather_api.fetch_weather()
    places.save({"name": "Denver", "latitude": 39.7392, "longitude": -104.9847})
    weather_api.fetch_weather()
    assert urls == ["https://example.test/?lat=39.5349&lon=-119.7527",
                    "https://example.test/?lat=39.7392&lon=-104.9847"]


def test_daylight_uses_only_the_current_location(seeded_db, db_conn):
    now = datetime.now(timezone.utc).replace(microsecond=0)

    def stamp(moment):
        return moment.strftime("%Y-%m-%d %H:%M:%S")

    db_conn.execute("DELETE FROM weather_readings")
    db_conn.executemany(
        "INSERT INTO weather_readings (measured_utc, latitude, longitude, sunrise_utc, sunset_utc) "
        "VALUES (?, ?, ?, ?, ?)",
        [(stamp(now - timedelta(hours=1)), 39.53, -119.75, "2026-01-01 14:00:00", "2026-01-02 01:00:00"),
         (stamp(now), 51.5, -0.12, "2026-01-01 07:00:00", "2026-01-01 16:00:00")])
    db_conn.commit()
    since = stamp(now - timedelta(days=1))
    assert len(db.sun_windows(since)) == 2
    london = {"latitude": 51.5085, "longitude": -0.1257}
    assert db.sun_windows(since, london) == [("2026-01-01 07:00:00", "2026-01-01 16:00:00")]


# --- Settings › Location ---------------------------------------------------------------


@pytest.fixture
def tab(seeded_db, monkeypatch):
    """Look-ups answer only "Denver"; fetching the weather is recorded instead of sent."""
    from services import weather_collector

    monkeypatch.setattr(places, "search", lambda name: [
        {"name": "Denver, Colorado, United States", "latitude": 39.7392, "longitude": -104.9847,
         "timezone": "America/Denver"}] if name == "Denver" else [])
    fetched = []
    monkeypatch.setattr(weather_collector, "collect_once", lambda: fetched.append(places.current()["name"]) or True)
    return fetched


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception, [e.message for e in at.exception]


def test_location_tab_shows_the_current_place(tab):
    at = run_section("location")
    assert not at.exception
    assert any("39.5349, -119.7527" in c.value for c in at.caption)
    assert "from the installer's settings" in at.caption[0].value


def test_location_tab_finds_and_uses_a_place(tab):
    at = run_section("location")
    at.text_input[0].input("Denver")
    click(at, "Find")
    assert at.radio[0].options == ["Denver, Colorado, United States (39.74, -104.98)"]
    assert "America/Denver" in at.checkbox[0].label
    click(at, "Use this location")
    assert places.current()["name"] == "Denver, Colorado, United States"
    assert tab == ["Denver, Colorado, United States"]  # the new place's weather was fetched straight away
    assert "Location set to Denver" in at.success[0].value
    assert at.session_state["timezone_name"] == "America/Denver"
    assert db.read_preferences()["timezone_name"] == "America/Denver"


def test_location_tab_can_keep_the_time_zone(tab):
    at = run_section("location")
    at.text_input[0].input("Denver")
    click(at, "Find")
    at.checkbox[0].uncheck()
    click(at, "Use this location")
    assert places.current()["name"] == "Denver, Colorado, United States"
    assert at.session_state["timezone_name"] != "America/Denver"


def test_location_tab_when_nothing_is_found(tab):
    at = run_section("location")
    at.text_input[0].input("Atlantis")
    click(at, "Find")
    assert "No place found" in at.warning[0].value


def test_location_tab_by_coordinates(tab):
    at = run_section("location")
    at.text_input[1].input("Allotment")
    at.number_input[0].set_value(51.5085)
    at.number_input[1].set_value(-0.1257)
    click(at, "Use these coordinates")
    now = places.current()
    assert (now["name"], now["latitude"], now["longitude"]) == ("Allotment", 51.5085, -0.1257)
    assert tab == ["Allotment"]


def test_set_location_script(seeded_db, capsys):
    from scripts import set_location

    assert set_location.main(["--latitude", "39.7392", "--longitude", "-104.9847", "--name", "Denver"]) == 0
    assert places.current()["name"] == "Denver" and "Location set to Denver" in capsys.readouterr().out
    assert set_location.main(["--latitude", "123", "--longitude", "0"]) == 2


# --- smarter search -------------------------------------------------------------------------


OM_SPARKS = [
    {"name": "Sparks", "admin1": "Nevada", "country": "United States", "country_code": "US", "feature_code": "PPL",
     "latitude": 39.5349, "longitude": -119.7527, "timezone": "America/Los_Angeles"},
    {"name": "Sparks", "admin1": "Georgia", "country": "United States", "country_code": "US", "feature_code": "PPL",
     "latitude": 31.19, "longitude": -83.44, "timezone": "America/New_York"},
    {"name": "Sparks Heliport", "admin1": "Nevada", "country": "United States", "country_code": "US",
     "feature_code": "AIRH", "latitude": 39.5, "longitude": -119.7, "timezone": "America/Los_Angeles"},
]


def open_meteo(answers):
    """A fake Open-Meteo: answers by the 'name' asked for; records the names."""
    import urllib.parse

    asked = []

    def fetch(url):
        name = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["name"][0]
        asked.append(name)
        found = {key.lower(): value for key, value in answers.items()}.get(name.lower(), [])  # case-insensitive
        return json.dumps({"results": found}).encode()

    fetch.asked = asked
    return fetch


class FakeGeocoder:
    def __init__(self, found=(), error=None):
        self.found, self.error, self.queries = list(found), error, []

    def geocode(self, query, **kwargs):
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.found


class FakeLocation:
    def __init__(self, lat, lon, address):
        self.latitude, self.longitude, self.address = lat, lon, "full address"
        self.raw = {"address": address}


def test_search_skips_places_that_are_not_towns():
    fetch = open_meteo({"Sparks": OM_SPARKS})
    names = [p["name"] for p in places.search("Sparks", fetch=fetch, geocoder=FakeGeocoder())]
    assert names == ["Sparks, Nevada, United States", "Sparks, Georgia, United States"]


@pytest.mark.parametrize("query", ["Sparks NV", "Sparks, NV", "sparks, nevada, usa", "Sparks, US"])
def test_search_with_a_state_or_country(query):
    fetch = open_meteo({"Sparks": OM_SPARKS})
    found = places.search(query, fetch=fetch, geocoder=FakeGeocoder())
    if query == "Sparks, US":
        assert len(found) == 2  # both US places
    else:
        assert [p["name"] for p in found] == ["Sparks, Nevada, United States"]
    assert fetch.asked[-1].lower() == "sparks"  # the town alone, after the full query found nothing


def test_search_falls_back_to_openstreetmap():
    geocoder = FakeGeocoder([FakeLocation(38.8977, -77.0365, {"city": "Washington", "state": "District of Columbia",
                                                              "country": "United States"})])
    found = places.search("1600 Pennsylvania Ave NW, Washington DC", fetch=open_meteo({}), geocoder=geocoder)
    assert found == [{"name": "Washington, District of Columbia, United States", "latitude": 38.8977,
                      "longitude": -77.0365, "timezone": None}]
    assert geocoder.queries == ["1600 Pennsylvania Ave NW, Washington DC"]


def test_search_fallback_failure_is_quiet():
    assert places.search("Nowhere at all", fetch=open_meteo({}), geocoder=FakeGeocoder(error=OSError("offline"))) == []


def test_openstreetmap_is_not_asked_when_open_meteo_finds_it():
    geocoder = FakeGeocoder()
    places.search("Sparks", fetch=open_meteo({"Sparks": OM_SPARKS}), geocoder=geocoder)
    assert geocoder.queries == []
