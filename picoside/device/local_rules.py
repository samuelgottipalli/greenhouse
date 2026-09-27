"""
Automation rules the controller applies by itself when the server can't
reach it ("local mode"), plus the settings they need.

They mirror ``server/core/automation.py`` so behaviour is the same with or
without the network:

* Fan: on above ``fan_on_temp_c`` or ``fan_on_humidity_pct``; once on, off
  only when both are at their trigger minus buffer.
* Heater: on below ``heater_on_temp_c``; off at trigger + buffer. **Off when
  there is no temperature** (sensor fault).
* Water: on during a watering slot (local time, may cross midnight), off
  otherwise; off when the clock is not set.

Settings arrive from the server on the retained ``<prefix>/<id>/settings``
topic and are saved to ``settings.json`` on the Pico's flash, so local mode
works after a reboot even with no network. Without settings, local mode only
enforces safety: heater and water off, fan left as it is.

A controller set up to run on its own (``standalone``, no server) gets its
settings from the setup page instead, starting from :func:`default_settings`
(the same defaults the server uses).
"""
import json

SETTINGS_FILE = "settings.json"
THRESHOLD_KEYS = ("fan_on_temp_c", "fan_on_humidity_pct", "heater_on_temp_c")
WATERING_SLOTS = 4


def default_settings():
    """
    The factory settings, the same as the server's defaults
    (``server/core/migrations.py``).

    Returns:
        dict: Settings in the format of :func:`valid_settings` (a new copy).
    """
    return {
        "fan_on_temp_c": [32.0, 2.0],
        "fan_on_humidity_pct": [50.0, 2.0],
        "heater_on_temp_c": [18.0, 2.0],
        "watering": [["06:00", 30], ["00:00", 0], ["00:00", 0], ["00:00", 0]],
    }


def valid_settings(payload):
    """
    Check a settings message from the server.

    Args:
        payload (object): Decoded JSON.

    Returns:
        bool: True if it has every threshold as ``[value, buffer]`` numbers
        and ``watering`` as a list of ``["HH:MM", minutes]``.
    """
    if not isinstance(payload, dict):
        return False
    for key in THRESHOLD_KEYS:
        pair = payload.get(key)
        if not isinstance(pair, list) or len(pair) != 2:
            return False
        for number in pair:
            if isinstance(number, bool) or not isinstance(number, (int, float)):
                return False
    watering = payload.get("watering")
    if not isinstance(watering, list):
        return False
    for slot in watering:
        if not isinstance(slot, list) or len(slot) != 2 or not isinstance(slot[0], str):
            return False
        if len(slot[0]) != 5 or slot[0][2] != ":" or not isinstance(slot[1], int):
            return False
    return True


def load_settings(filename=SETTINGS_FILE):
    """
    Load settings saved by :func:`save_settings`.

    Returns:
        dict | None: Settings, or None if missing or invalid.
    """
    try:
        with open(filename, "r") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    return payload if valid_settings(payload) else None


def save_settings(payload, filename=SETTINGS_FILE):
    """
    Save settings to flash.

    Args:
        payload (dict): Valid settings.

    Returns:
        bool: True if written.
    """
    try:
        with open(filename, "w") as f:
            json.dump(payload, f)
    except OSError as err:
        print("Could not save settings:", err)
        return False
    return True


def fan_target(limits, temp, humidity, is_on):
    """
    Decide the fan state.

    Returns:
        bool | None: Target, or None to leave it as it is (no readings).
    """
    t_on, t_buf = limits["fan_on_temp_c"]
    h_on, h_buf = limits["fan_on_humidity_pct"]
    if temp is None and humidity is None:
        return None
    if (temp is not None and temp > t_on) or (humidity is not None and humidity > h_on):
        return True
    if not is_on:
        return False
    cool = temp is None or temp <= t_on - t_buf
    dry = humidity is None or humidity <= h_on - h_buf
    return not (cool and dry)


def heater_target(limits, temp, is_on):
    """
    Decide the heater state; off without a temperature.

    Returns:
        bool: Target.
    """
    if temp is None:
        return False
    trigger, buffer = limits["heater_on_temp_c"]
    if temp < trigger:
        return True
    return is_on and temp < trigger + buffer


def watering_now(schedule, local_minutes):
    """
    Tell whether a watering slot covers a local time of day.

    Args:
        schedule (list): ``[["HH:MM", minutes], ...]``.
        local_minutes (int | None): Minutes since local midnight; None if the
            clock is not set.

    Returns:
        bool: True inside a slot (start inclusive, end exclusive).
    """
    if local_minutes is None:
        return False
    for start_text, minutes in schedule:
        if minutes <= 0:
            continue
        start = int(start_text[:2]) * 60 + int(start_text[3:])
        if (local_minutes - start) % 1440 < minutes:
            return True
    return False


def decide(settings, temp, humidity, states, local_minutes):
    """
    Work out local-mode relay targets.

    Args:
        settings (dict | None): Last settings from the server.
        temp (float | None): Fresh temperature in °C, or None.
        humidity (float | None): Fresh humidity in %, or None.
        states (dict): Relay name to current state (0/1).
        local_minutes (int | None): Minutes since local midnight.

    Returns:
        dict: Relay name to target state (0/1) for relays that should be set.
    """
    if settings is None:
        return {"heater": 0, "water": 0}
    targets = {
        "heater": heater_target(settings, temp, states.get("heater") == 1),
        "water": watering_now(settings["watering"], local_minutes),
    }
    fan = fan_target(settings, temp, humidity, states.get("fan") == 1)
    if fan is not None:
        targets["fan"] = fan
    return {name: 1 if on else 0 for name, on in targets.items()}
