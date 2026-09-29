"""
The greenhouse's location, used for the outdoor weather and for sunrise and
sunset (which decide when the grow light may run).

It is chosen on Settings › Location (or by the installer) and stored in the
``app_preferences`` table under ``LOCATION_KEYS``. Without a stored choice the
``LATITUDE``/``LONGITUDE`` settings from ``.env`` are used. The weather
collector reads it before every fetch, so a change applies from the next
reading without restarting anything.

Places are looked up with Open-Meteo's free geocoding service, which also
gives each place's time zone. It matches a place name or postcode ("Sparks",
"89431"); :func:`search` also understands a state or country after it
("Sparks, NV", "Paris France", with common abbreviations), and falls back to
OpenStreetMap's Nominatim service (through ``geopy``) for anything else, such
as a street address. Standard library only apart from that optional
fallback, so the installer can use it too.
"""
import json
import urllib.parse
import urllib.request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
LOCATION_KEYS = {"name": "location_name", "latitude": "location_latitude",
                 "longitude": "location_longitude", "timezone": "location_timezone"}
# Open-Meteo answers with the nearest point of its weather grid, a few km from
# the requested spot; readings within this many degrees belong to the place.
SAME_PLACE_DEGREES = 0.25


# Abbreviations people type after a town, matched against Open-Meteo's state and country.
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
COUNTRY_WORDS = {"USA": "US", "UK": "GB", "UAE": "AE"}
NOMINATIM_AGENT = "greenhouse-dashboard (https://github.com/samuelgottipalli/greenhouse)"


def _open_meteo(name: str, fetch, count: int) -> list[dict]:
    """Raw Open-Meteo matches for a name or postcode (towns and regions only)."""
    url = GEOCODE_URL + "?" + urllib.parse.urlencode({"name": name, "count": count, "language": "en"})
    try:
        data = json.loads(fetch(url))
    except (OSError, ValueError):
        return []
    items = data.get("results") or []
    # Populated places and regions; not airports, hospitals, mountains, ...
    return [item for item in items if str(item.get("feature_code", "PPL")).startswith(("PPL", "ADM"))]


def _place(item: dict) -> dict | None:
    """An Open-Meteo match as a place, or None if it has no usable position."""
    try:
        latitude, longitude = round(float(item["latitude"]), 4), round(float(item["longitude"]), 4)
    except (KeyError, TypeError, ValueError):
        return None
    parts = [item.get("name"), item.get("admin1"), item.get("country")]
    return {"name": ", ".join(p for p in parts if p), "latitude": latitude, "longitude": longitude,
            "timezone": item.get("timezone") or "UTC"}


def _matches(item: dict, qualifiers: list[str]) -> bool:
    """Tell whether every word after the town ("NV", "Nevada", "USA") fits a match."""
    fields = {str(item.get(key, "")).lower() for key in ("admin1", "admin2", "admin3", "country", "country_code")}
    for word in qualifiers:
        upper = word.upper()
        wanted = {word.lower(), US_STATES.get(upper, "").lower(), COUNTRY_WORDS.get(upper, "").lower()} - {""}
        if not wanted & fields:
            return False
    return True


def _split(query: str) -> tuple[str, list[str]] | None:
    """Split "Sparks, NV" or "Sparks NV" into the town and what follows; None for one word."""
    if "," in query:
        town, *rest = [part.strip() for part in query.split(",")]
        return (town, [part for part in rest if part]) if town and rest else None
    words = query.split()
    return (" ".join(words[:-1]), words[-1:]) if len(words) > 1 else None


def _nominatim(query: str, count: int, geocoder=None) -> list[dict]:
    """
    OpenStreetMap's Nominatim, through geopy, for queries Open-Meteo can't
    place (addresses, unusual spellings). No time zone comes with these.
    """
    try:
        if geocoder is None:
            from geopy.geocoders import Nominatim

            geocoder = Nominatim(user_agent=NOMINATIM_AGENT, timeout=10)
        found = geocoder.geocode(query, exactly_one=False, limit=count, addressdetails=True, language="en")
    except Exception:  # geopy missing, offline, rate-limited, ...
        return []
    places = []
    for location in found or []:
        address = (getattr(location, "raw", None) or {}).get("address", {})
        town = address.get("city") or address.get("town") or address.get("village") or address.get("hamlet")
        parts = [town, address.get("state"), address.get("country")]
        name = ", ".join(p for p in parts if p) or location.address
        places.append({"name": name, "latitude": round(location.latitude, 4),
                       "longitude": round(location.longitude, 4), "timezone": None})
    return places


def search(query: str, fetch=None, count: int = 8, geocoder=None) -> list[dict]:
    """
    Find places by name, postcode or address.

    1. Open-Meteo with the query as typed ("Sparks", "Sparks, Nevada", "89431").
    2. With nothing found: the town alone, keeping matches whose state or
       country fits the rest ("Sparks, NV", "Paris France", "Leeds UK").
    3. Still nothing: OpenStreetMap's Nominatim (addresses and the like).

    Args:
        query (str): What was typed.
        fetch (callable | None): ``fetch(url) -> bytes`` for Open-Meteo (injected in tests).
        count (int): Most places to return.
        geocoder: A geopy geocoder for step 3 (injected in tests).

    Returns:
        list[dict]: Places with ``name`` (e.g. ``"Sparks, Nevada, United
        States"``), ``latitude``, ``longitude`` and ``timezone`` (None from
        step 3); empty if none, or when offline.
    """
    query = " ".join(query.split())
    if not query:
        return []
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=10).read())
    items = _open_meteo(query, fetch, count)
    split = None if items else _split(query)
    if split:
        town, qualifiers = split
        items = [item for item in _open_meteo(town, fetch, 50) if _matches(item, qualifiers)][:count]
    places = [place for place in map(_place, items) if place]
    return places or _nominatim(query, count, geocoder)


def valid(latitude, longitude) -> bool:
    """Tell whether a latitude and longitude are numbers on the globe."""
    try:
        return -90 <= float(latitude) <= 90 and -180 <= float(longitude) <= 180
    except (TypeError, ValueError):
        return False


def current(preferences: dict[str, str] | None = None) -> dict | None:
    """
    The location in use.

    Args:
        preferences (dict | None): Stored preferences (default: read from the database).

    Returns:
        dict | None: ``name``, ``latitude``, ``longitude``, ``timezone``
        (may be None) and ``source`` (``"dashboard"`` or ``"settings"``);
        None when no location is set anywhere.
    """
    from core import settings

    if preferences is None:
        from core import db

        preferences = db.read_preferences()
    stored = {field: preferences.get(key) for field, key in LOCATION_KEYS.items()}
    if valid(stored["latitude"], stored["longitude"]):
        return {"name": stored["name"] or f"{float(stored['latitude']):.4f}, {float(stored['longitude']):.4f}",
                "latitude": float(stored["latitude"]), "longitude": float(stored["longitude"]),
                "timezone": stored["timezone"] or None, "source": "dashboard"}
    if valid(settings.LATITUDE, settings.LONGITUDE):
        latitude, longitude = float(settings.LATITUDE), float(settings.LONGITUDE)
        return {"name": f"{latitude:.4f}, {longitude:.4f}", "latitude": latitude, "longitude": longitude,
                "timezone": settings.TIMEZONE, "source": "settings"}
    return None


def save(place: dict) -> bool:
    """
    Store a new location (it applies from the next weather reading).

    Args:
        place (dict): ``name``, ``latitude``, ``longitude`` and optionally ``timezone``.

    Returns:
        bool: True if stored.

    Raises:
        ValueError: If the position isn't valid.
    """
    from core import db

    if not valid(place.get("latitude"), place.get("longitude")):
        raise ValueError("latitude must be -90 to 90 and longitude -180 to 180")
    return db.save_preferences({
        LOCATION_KEYS["name"]: place.get("name") or "",
        LOCATION_KEYS["latitude"]: f"{float(place['latitude']):.4f}",
        LOCATION_KEYS["longitude"]: f"{float(place['longitude']):.4f}",
        LOCATION_KEYS["timezone"]: place.get("timezone") or "",
    })


def near(latitude: float, longitude: float, place: dict | None) -> bool:
    """
    Tell whether a weather reading's position belongs to a place.

    Args:
        latitude (float): The reading's latitude (Open-Meteo's grid point).
        longitude (float): The reading's longitude.
        place (dict | None): From :func:`current`; None matches everything.

    Returns:
        bool: True if within ``SAME_PLACE_DEGREES`` of the place.
    """
    if place is None:
        return True
    return (abs(float(latitude) - place["latitude"]) <= SAME_PLACE_DEGREES
            and abs(float(longitude) - place["longitude"]) <= SAME_PLACE_DEGREES)
