"""
Background automation service that switches relays based on thresholds.

Run from the ``server/`` folder with ``python -m services.automation``. Every
5 seconds it reads the current thresholds and watering schedule, the latest
sensor readings and the latest relay states, then:

* Fan: on above ``fan_on_humidity_pct`` or ``fan_on_temp_c``, off once below
  the trigger minus its buffer.
* Heater: on below ``heater_on_temp_c``, otherwise off.
* Water: on during any watering slot (``start_local`` + ``duration_min``),
  otherwise off.
* Light: not implemented.

Each change is published over MQTT and logged with source ``"auto"``.

This is a straight port of the original loop to the version 2 schema. Its
known defects are marked ``S-06`` below and listed in docs/FINDINGS.md; the
loop is rewritten as a tested pure function in PLAN step 1.1.
"""
import logging
from datetime import datetime as dtt
from datetime import timedelta
from time import sleep

from core import db
from core.mqtt import publish_relay_command
from core.timeutil import parse_time_of_day

log = logging.getLogger(__name__)

FAN, HEATER, WATER = 2, 3, 1


def switch(publish_relay: int, log_relay: int, state: int) -> None:
    """
    Publish a relay command and log it as an automatic change.

    Args:
        publish_relay (int): Relay the MQTT command is sent to.
        log_relay (int): Relay recorded in ``relay_events``. Always equal to
            ``publish_relay`` except for the heater defect (S-06 1).
        state (int): 1 for on, 0 for off.
    """
    publish_relay_command(relay_id=publish_relay, state=state, source="auto")
    db.log_relay_event(relay_id=log_relay, state=state, source="auto")


def watering_windows(schedule, now: dtt) -> list[tuple[dtt, dtt]]:
    """
    Turn the watering schedule into today's (start, end) windows.

    Args:
        schedule (DataFrame): Output of ``db.read_watering_schedule()``.
        now (dtt): Current local time (naive).

    Returns:
        list[tuple[datetime, datetime]]: One window per slot.
    """
    windows = []
    for start_local, minutes in zip(schedule["start_local"], schedule["duration_min"]):
        start = dtt.combine(now.date(), parse_time_of_day(start_local))
        windows.append((start, start + timedelta(minutes=int(minutes))))
    return windows


def main() -> None:
    """Run the automation loop forever."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        thresholds = db.read_thresholds()
        schedule = db.read_watering_schedule()
        readings = db.latest_sensor_readings()
        relay_states = db.latest_relay_states()
        currenttime = dtt.now()

        if thresholds is None or schedule is None or readings is None or relay_states is None:
            continue  # S-06 (4): no sleep, so this spins while data is missing

        limit = thresholds.set_index("name")
        fan_on_temp_val, fan_on_temp_buffer_val = limit.loc["fan_on_temp_c", ["value", "buffer"]]
        heater_on_temp_val, heater_on_temp_buffer_val = limit.loc["heater_on_temp_c", ["value", "buffer"]]
        fan_on_humidity_val, fan_on_humidity_buffer_val = limit.loc["fan_on_humidity_pct", ["value", "buffer"]]

        value = dict(zip(readings["measure"], readings["value"]))
        greenhouse_temp = value["temperature"]  # S-01: no check on how old this is
        greenhouse_humidity = value["humidity"]

        state = dict(zip(relay_states["relay_id"], relay_states["state"]))
        fan_on, heater_on, water_on = state[FAN] == 1, state[HEATER] == 1, state[WATER] == 1

        # S-06 (2): humidity and temperature blocks can both switch the fan in one pass.
        if greenhouse_humidity > fan_on_humidity_val:
            if not fan_on:
                switch(FAN, FAN, 1)
        elif fan_on and not greenhouse_temp > fan_on_temp_val - fan_on_temp_buffer_val:
            switch(FAN, FAN, 0)

        if greenhouse_temp > fan_on_temp_val:
            if not fan_on:
                switch(FAN, FAN, 1)
        # S-06 (2): compares temperature with the humidity threshold.
        elif fan_on and not greenhouse_temp > fan_on_humidity_val - fan_on_humidity_buffer_val:
            switch(FAN, FAN, 0)

        # S-06 (1): heater commands are published to the fan relay.
        # S-06 (3): heater_on_temp_buffer_val is never used.
        if greenhouse_temp < heater_on_temp_val:
            if not heater_on:
                switch(FAN, HEATER, 1)
        elif heater_on:
            switch(FAN, HEATER, 0)

        watering = any(start <= currenttime <= end for start, end in watering_windows(schedule, currenttime))
        if watering and not water_on:
            switch(WATER, WATER, 1)
        elif not watering and water_on:
            switch(WATER, WATER, 0)

        sleep(5)


if __name__ == "__main__":
    main()
