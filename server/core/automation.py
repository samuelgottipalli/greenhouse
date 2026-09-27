"""
Automation rules: decide which relays to switch, given settings, readings,
current relay states and the time. Pure functions only (no database or MQTT),
so every rule is unit-tested; ``services/automation.py`` feeds them and acts on
the result.

Rules
-----
* **Fan** (hysteresis): turns on when temperature > ``fan_on_temp_c`` or
  humidity > ``fan_on_humidity_pct``. Once on, it stays on until both are at or
  below their trigger minus buffer. A stale or missing measure is ignored; if
  both are stale the fan is left as it is.
* **Heater** (hysteresis): turns on when temperature < ``heater_on_temp_c`` and
  off when it reaches trigger + buffer. **If the temperature is stale or
  missing, the heater is switched off**: a heater should never run without
  fresh feedback.
* **Water**: on during any watering slot (local ``start_local`` +
  ``duration_min``; a slot may run past midnight), otherwise off.
* **Manual override**: a relay last switched from the web app or a device
  button is left alone for ``MANUAL_OVERRIDE`` after that change.
* **Light** (grow lamp): off at night (outside sunrise-sunset from the
  weather data). In daytime, on when the raw light level is below
  ``light_on_level`` and off again above level + buffer; the buffer must be
  larger than the lamp's own light reaching the sensor. At most one daytime
  switch per ``LIGHT_MIN_SWITCH`` so it can never flicker. Without sunrise and
  sunset data, or without a fresh light reading in daytime, it is left as
  it is. Not part of the controller's local mode (it has no sunrise data).
* **Controller offline**: nothing is decided. Commands to a disconnected
  controller are dropped by the broker, and the controller runs the same
  rules itself in local mode (``picoside/device/local_rules.py``) with the
  settings from :func:`device_settings`.

A relay with no recorded state gets its target state once, so the log and the
device agree from the start.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

READING_MAX_AGE = timedelta(minutes=15)
MANUAL_OVERRIDE = timedelta(minutes=60)
LIGHT_MIN_SWITCH = timedelta(minutes=30)
MANUAL_SOURCES = ("web", "device")


@dataclass(frozen=True)
class Reading:
    """One sensor value and when it was measured (aware UTC datetime)."""

    value: float
    at: datetime


@dataclass(frozen=True)
class RelayState:
    """Last logged state of a relay: 1/0, who set it, and when (aware UTC)."""

    state: int
    source: str
    at: datetime


@dataclass(frozen=True)
class Action:
    """A relay change the service should make, with a reason for the log."""

    relay: str
    state: int
    reason: str


def fresh_value(readings: dict[str, Reading], measure: str, now: datetime) -> float | None:
    """
    Return a reading's value if it exists and is recent enough.

    Args:
        readings (dict[str, Reading]): Latest reading per measure name.
        measure (str): e.g. ``"temperature"``.
        now (datetime): Current time (aware).

    Returns:
        float | None: The value, or None if missing or older than
        ``READING_MAX_AGE``.
    """
    reading = readings.get(measure)
    if reading is None or now - reading.at > READING_MAX_AGE:
        return None
    return reading.value


def fan_target(thresholds: dict[str, tuple[float, float]], temp: float | None,
               humidity: float | None, is_on: bool) -> tuple[bool | None, str]:
    """
    Decide the fan state.

    Args:
        thresholds (dict): Name to ``(value, buffer)``.
        temp (float | None): Fresh temperature in °C, or None.
        humidity (float | None): Fresh relative humidity in %, or None.
        is_on (bool): Whether the fan is on now.

    Returns:
        tuple[bool | None, str]: Target (None = leave as is) and a reason.
    """
    t_on, t_buf = thresholds["fan_on_temp_c"]
    h_on, h_buf = thresholds["fan_on_humidity_pct"]
    if temp is None and humidity is None:
        return None, "no fresh temperature or humidity"
    too_hot = temp is not None and temp > t_on
    too_humid = humidity is not None and humidity > h_on
    if too_hot or too_humid:
        return True, f"temperature {temp} / humidity {humidity} above trigger"
    if not is_on:
        return False, "below triggers"
    cool = temp is None or temp <= t_on - t_buf
    dry = humidity is None or humidity <= h_on - h_buf
    if cool and dry:
        return False, "below triggers minus buffers"
    return True, "within buffer, staying on"


def heater_target(thresholds: dict[str, tuple[float, float]], temp: float | None,
                  is_on: bool) -> tuple[bool, str]:
    """
    Decide the heater state.

    Args:
        thresholds (dict): Name to ``(value, buffer)``.
        temp (float | None): Fresh temperature in °C, or None.
        is_on (bool): Whether the heater is on now.

    Returns:
        tuple[bool, str]: Target and a reason.
    """
    if temp is None:
        return False, "no fresh temperature (safety off)"
    trigger, buffer = thresholds["heater_on_temp_c"]
    if temp < trigger:
        return True, f"temperature {temp} below {trigger}"
    if is_on and temp < trigger + buffer:
        return True, "within buffer, staying on"
    return False, f"temperature {temp} at or above {trigger + (buffer if is_on else 0)}"


def light_target(
    thresholds: dict[str, tuple[float, float]],
    light: float | None,
    is_on: bool,
    daylight: bool | None,
    since_change: timedelta | None,
) -> tuple[bool | None, str]:
    """
    Decide the grow light state.

    Args:
        thresholds (dict): Name to ``(value, buffer)``; uses ``light_on_level``.
        light (float | None): Fresh raw light level (brighter = higher), or None.
        is_on (bool): Whether the light is on now.
        daylight (bool | None): True between sunrise and sunset, None if unknown.
        since_change (timedelta | None): Time since the light was last switched.

    Returns:
        tuple[bool | None, str]: Target (None = leave as is) and a reason.
    """
    if daylight is None:
        return None, "no sunrise/sunset data"
    if not daylight:
        return False, "night"
    if light is None:
        return None, "no fresh light reading"
    if since_change is not None and since_change < LIGHT_MIN_SWITCH:
        return None, "switched less than 30 min ago"
    level, buffer = thresholds["light_on_level"]
    if not is_on:
        return light < level, f"light {light:.0f} vs on-level {level:.0f}"
    if light > level + buffer:
        return False, f"light {light:.0f} above {level + buffer:.0f}"
    return True, "within buffer, staying on"


def is_daylight(sun_windows: list[tuple[datetime, datetime]], now: datetime) -> bool | None:
    """
    Tell whether it is daytime, from sunrise/sunset pairs in the weather data.

    Args:
        sun_windows (list): ``(sunrise, sunset)`` pairs (aware UTC) from recent
            weather readings; several days may be present.
        now (datetime): Current time (aware).

    Returns:
        bool | None: True inside any sunrise-sunset window, False outside all
        of them, None when there are no windows.
    """
    if not sun_windows:
        return None
    return any(sunrise <= now < sunset for sunrise, sunset in sun_windows)


def watering_now(schedule: list[tuple[str, int]], now_local: datetime) -> bool:
    """
    Tell whether any watering slot covers a local time.

    Checks each slot's window starting today and yesterday, so a slot that
    runs past midnight is honoured.

    Args:
        schedule (list[tuple[str, int]]): ``(start "HH:MM", duration_min)``.
        now_local (datetime): Current local time (naive or aware).

    Returns:
        bool: True inside a window (start inclusive, end exclusive).
    """
    naive = now_local.replace(tzinfo=None)
    for start_text, minutes in schedule:
        if minutes <= 0:
            continue
        hour, minute = (int(p) for p in start_text.split(":"))
        for day in (naive.date(), naive.date() - timedelta(days=1)):
            start = datetime.combine(day, time(hour, minute))
            if start <= naive < start + timedelta(minutes=minutes):
                return True
    return False


def device_settings(thresholds: dict[str, tuple[float, float]], schedule: list[tuple[str, int]]) -> dict:
    """
    Build the settings message the controller keeps for local mode.

    Args:
        thresholds (dict): Threshold name to ``(value, buffer)``.
        schedule (list): Watering slots, ``(start_local, duration_min)``.

    Returns:
        dict: ``fan_on_temp_c``, ``fan_on_humidity_pct`` and
        ``heater_on_temp_c`` as ``[value, buffer]``, and ``watering`` as
        ``[["HH:MM", minutes], ...]``.
    """
    payload = {name: [float(v), float(b)] for name, (v, b) in thresholds.items()
               if name in ("fan_on_temp_c", "fan_on_humidity_pct", "heater_on_temp_c")}
    payload["watering"] = [[start, int(minutes)] for start, minutes in schedule]
    return payload


def decide(
    thresholds: dict[str, tuple[float, float]],
    schedule: list[tuple[str, int]],
    readings: dict[str, Reading],
    states: dict[str, RelayState],
    now: datetime,
    zone: tzinfo,
    device_online: bool = True,
    daylight: bool | None = None,
) -> list[Action]:
    """
    Work out which relays to switch.

    Args:
        thresholds (dict): Threshold name to ``(value, buffer)``.
        schedule (list): Watering slots, ``(start_local, duration_min)``.
        readings (dict[str, Reading]): Latest reading per measure name.
        states (dict[str, RelayState]): Latest state per relay name
            (``"fan"``, ``"heater"``, ``"water"``); missing means unknown.
        now (datetime): Current time, aware.
        zone (tzinfo): Zone of the watering schedule.
        device_online (bool): False while the controller reports offline;
            then nothing is decided (its local mode is in charge).
        daylight (bool | None): From :func:`is_daylight`; None leaves the
            light alone.

    Returns:
        list[Action]: Changes to make, at most one per relay.
    """
    if not device_online:
        return []
    temp = fresh_value(readings, "temperature", now)
    humidity = fresh_value(readings, "humidity", now)
    targets = {
        "fan": fan_target(thresholds, temp, humidity, _is_on(states, "fan")),
        "heater": heater_target(thresholds, temp, _is_on(states, "heater")),
        "water": (watering_now(schedule, now.astimezone(zone)), "watering schedule"),
    }
    if "light_on_level" in thresholds:
        light_state = states.get("light")
        targets["light"] = light_target(
            thresholds,
            fresh_value(readings, "light_raw", now),
            _is_on(states, "light"),
            daylight,
            None if light_state is None else now - light_state.at,
        )
    actions = []
    for relay, (target, reason) in targets.items():
        current = states.get(relay)
        if target is None or _manually_held(current, now):
            continue
        if current is None or bool(current.state) != target:
            actions.append(Action(relay, 1 if target else 0, reason))
    return actions


def _is_on(states: dict[str, RelayState], relay: str) -> bool:
    """Tell whether a relay's last known state is on."""
    return relay in states and states[relay].state == 1


def _manually_held(current: RelayState | None, now: datetime) -> bool:
    """Tell whether a recent manual change should be respected."""
    return current is not None and current.source in MANUAL_SOURCES and now - current.at < MANUAL_OVERRIDE
