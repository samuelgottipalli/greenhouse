"""
The greenhouse's location, used for the outdoor weather and for sunrise and
sunset (which decide when the grow light may run).

It is chosen on Settings › Location (or by the installer) and stored in the
``app_preferences`` table under ``LOCATION_KEYS``. Without a stored choice the
``LATITUDE``/``LONGITUDE`` settings from ``.env`` are used. The weather
collector reads it before every fetch, so a change applies from the next
reading without restarting anything.

Places are looked up by name with Open-Meteo's free geocoding service
(:func:`search`, standard library only so the installer can use it too).
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


def search(name: str, fetch=None, count: int = 8) -> list[dict]:
    """
    Find places by name (Open-Meteo geocoding, no account needed).

    Args:
        name (str): Town or city, e.g. ``"Reno"``.
        fetch (callable | None): ``fetch(url) -> bytes`` (injected in tests).
        count (int): Most places to return.

    Returns:
        list[dict]: Places with ``name`` (e.g. ``"Sparks, Nevada, United
        States"``), ``latitude``, ``longitude`` and ``timezone``; empty if
        none, or when offline.
    """
    if not name.strip():
        return []
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=10).read())
    url = GEOCODE_URL + "?" + urllib.parse.urlencode({"name": name.strip(), "count": count, "language": "en"})
    try:
        data = json.loads(fetch(url))
    except (OSError, ValueError):
        return []
    places = []
    for item in data.get("results") or []:
        try:
            latitude, longitude = round(float(item["latitude"]), 4), round(float(item["longitude"]), 4)
        except (KeyError, TypeError, ValueError):
            continue
        parts = [item.get("name"), item.get("admin1"), item.get("country")]
        places.append({"name": ", ".join(p for p in parts if p), "latitude": latitude,
                       "longitude": longitude, "timezone": item.get("timezone") or "UTC"})
    return places


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
