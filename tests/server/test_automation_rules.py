"""Table-driven tests for server/core/automation.py (S-06, S-01 stale guard)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from core.automation import (
    MANUAL_OVERRIDE,
    READING_MAX_AGE,
    Action,
    Reading,
    RelayState,
    decide,
    fan_target,
    heater_target,
    watering_now,
)

NOW = datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc)  # 12:00 in Los Angeles
LA = ZoneInfo("America/Los_Angeles")
LIMITS = {
    "fan_on_temp_c": (30.0, 2.0),
    "fan_on_humidity_pct": (70.0, 5.0),
    "heater_on_temp_c": (10.0, 2.0),
    "light_on_level": (3.0, 0.0),
}
NO_WATER = [("06:00", 0)]


def readings(temp=None, humidity=None, age=timedelta(minutes=1)):
    out = {}
    if temp is not None:
        out["temperature"] = Reading(temp, NOW - age)
    if humidity is not None:
        out["humidity"] = Reading(humidity, NOW - age)
    return out


def states(fan=0, heater=0, water=0, source="auto", age=timedelta(hours=2)):
    return {name: RelayState(value, source, NOW - age)
            for name, value in (("fan", fan), ("heater", heater), ("water", water))}


# --- fan ------------------------------------------------------------------

@pytest.mark.parametrize(
    "temp, humidity, is_on, expected",
    [
        (31, 50, False, True),     # too hot
        (25, 71, False, True),     # too humid
        (30, 70, False, False),    # exactly at triggers: not above
        (29, 69, True, True),      # within both buffers: stay on
        (28, 69, True, True),      # temp cool enough, humidity still in buffer
        (28, 65, True, False),     # both at trigger minus buffer: off
        (29, 50, True, True),      # temp in buffer
        (None, 71, False, True),   # humidity alone can trigger
        (28, None, True, False),   # humidity stale: temperature decides
        (None, None, True, None),  # nothing fresh: hold
    ],
)
def test_fan_target(temp, humidity, is_on, expected):
    assert fan_target(LIMITS, temp, humidity, is_on)[0] is expected


# --- heater ----------------------------------------------------------------

@pytest.mark.parametrize(
    "temp, is_on, expected",
    [
        (9.9, False, True),    # below trigger
        (10, False, False),    # at trigger: stays off
        (11, True, True),      # within buffer (10..12): stays on (S-06 3)
        (12, True, False),     # reached trigger + buffer
        (11, False, False),    # off and above trigger
        (None, True, False),   # stale: safety off
        (None, False, False),
    ],
)
def test_heater_target(temp, is_on, expected):
    assert heater_target(LIMITS, temp, is_on)[0] is expected


# --- water ----------------------------------------------------------------

@pytest.mark.parametrize(
    "schedule, local, expected",
    [
        ([("06:00", 30)], "06:00", True),
        ([("06:00", 30)], "06:29", True),
        ([("06:00", 30)], "06:30", False),
        ([("06:00", 30)], "05:59", False),
        ([("23:50", 20)], "00:05", True),   # crosses midnight
        ([("23:50", 20)], "00:10", False),
        ([("06:00", 0)], "06:00", False),   # disabled slot
        ([("06:00", 0), ("18:00", 15)], "18:10", True),
    ],
)
def test_watering_now(schedule, local, expected):
    hour, minute = (int(p) for p in local.split(":"))
    assert watering_now(schedule, datetime(2026, 9, 27, hour, minute)) is expected


def test_watering_uses_schedule_zone():
    # 13:15 UTC is 06:15 in Los Angeles (PDT).
    now = datetime(2026, 9, 26, 13, 15, tzinfo=timezone.utc)
    actions = decide(LIMITS, [("06:00", 30)], readings(20, 50), states(), now, LA)
    assert Action("water", 1, "watering schedule") in actions


# --- decide ----------------------------------------------------------------

def relays(actions):
    return {a.relay: a.state for a in actions}


def test_nothing_to_do():
    assert decide(LIMITS, NO_WATER, readings(20, 50), states(), NOW, LA) == []


def test_cold_turns_heater_on_relay_by_name():
    # Formerly S-06 (1): heater commands went to the fan relay.
    assert relays(decide(LIMITS, NO_WATER, readings(5, 50), states(), NOW, LA)) == {"heater": 1}


def test_fan_switched_once_per_pass():
    # Formerly S-06 (2): humidity and temperature blocks could both send a command.
    actions = decide(LIMITS, NO_WATER, readings(35, 90), states(), NOW, LA)
    assert relays(actions) == {"fan": 1}
    assert len(actions) == 1


def test_stale_readings_turn_heater_off_and_hold_fan():
    old = readings(5, 90, age=READING_MAX_AGE + timedelta(seconds=1))
    actions = decide(LIMITS, NO_WATER, old, states(fan=1, heater=1), NOW, LA)
    assert relays(actions) == {"heater": 0}


def test_missing_readings():
    assert relays(decide(LIMITS, NO_WATER, {}, states(heater=1), NOW, LA)) == {"heater": 0}


def test_recent_manual_change_is_respected():
    # Formerly S-06 (5): automation reverted manual toggles within seconds.
    manual = states(fan=1, source="web", age=timedelta(minutes=5))
    assert decide(LIMITS, NO_WATER, readings(20, 50), manual, NOW, LA) == []


def test_manual_override_expires():
    manual = states(fan=1, source="device", age=MANUAL_OVERRIDE + timedelta(seconds=1))
    assert relays(decide(LIMITS, NO_WATER, readings(20, 50), manual, NOW, LA)) == {"fan": 0}


def test_unknown_relay_state_gets_target_once():
    actions = decide(LIMITS, NO_WATER, readings(20, 50), {}, NOW, LA)
    assert relays(actions) == {"fan": 0, "heater": 0, "water": 0}
