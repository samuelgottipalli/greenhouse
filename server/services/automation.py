"""
Background automation service.

Run from the ``server/`` folder with ``python -m services.automation``. Every
``POLL_SECONDS`` it loads the current thresholds, watering schedule, latest
sensor readings and latest relay states, asks ``core.automation.decide`` what
to change, and for each change publishes an MQTT command and logs a relay
event with source ``"auto"``. The rules themselves (hysteresis, stale-data
safety, manual override, watering windows) are documented and tested in
``core/automation.py``.

If settings or relays cannot be read, it logs a warning and waits for the
next pass instead of spinning.
"""
import logging
from datetime import datetime, timezone
from time import sleep
from zoneinfo import ZoneInfo

from core import db, settings
from core.automation import Reading, RelayState, decide
from core.mqtt import publish_relay_command
from core.timeutil import parse_utc_timestamp

log = logging.getLogger(__name__)

POLL_SECONDS = 5


def load_inputs(device_id: int = settings.DEVICE_ID):
    """
    Read everything ``decide`` needs from the database.

    Args:
        device_id (int): Device to automate.

    Returns:
        tuple | None: ``(thresholds, schedule, readings, states, relay_ids)``,
        or None if settings or relays are missing.
    """
    thresholds = db.read_thresholds(device_id=device_id)
    schedule = db.read_watering_schedule(device_id=device_id)
    names = db.relay_names(device_id=device_id)
    if thresholds is None or schedule is None or names is None:
        return None
    limits = {row.name: (row.value, row.buffer) for row in thresholds.itertuples()}
    slots = list(zip(schedule["start_local"], schedule["duration_min"].astype(int)))
    rows = db.latest_sensor_readings(device_id=device_id)
    readings = {} if rows is None else {
        r.measure: Reading(r.value, parse_utc_timestamp(r.reading_utc)) for r in rows.itertuples()
    }
    events = db.latest_relay_states(device_id=device_id)
    states = {} if events is None else {
        e.relay: RelayState(int(e.state), e.source, parse_utc_timestamp(e.event_utc)) for e in events.itertuples()
    }
    relay_ids = {name: relay_id for relay_id, name in names.items()}
    return limits, slots, readings, states, relay_ids


def run_once(now: datetime | None = None, device_id: int = settings.DEVICE_ID) -> list:
    """
    Do one automation pass.

    Args:
        now (datetime | None): Current time (aware); defaults to now in UTC.
        device_id (int): Device to automate.

    Returns:
        list[Action]: The changes made (empty if nothing to do or inputs missing).
    """
    inputs = load_inputs(device_id)
    if inputs is None:
        log.warning("Settings or relays missing; run `python -m scripts.upgrade_db`")
        return []
    limits, slots, readings, states, relay_ids = inputs
    now = now or datetime.now(timezone.utc)
    actions = decide(limits, slots, readings, states, now, ZoneInfo(settings.TIMEZONE))
    for action in actions:
        relay_id = relay_ids[action.relay]
        log.info("Switching %s %s: %s", action.relay, "on" if action.state else "off", action.reason)
        publish_relay_command(relay_id=relay_id, state=action.state, source="auto", device_id=device_id)
        db.log_relay_event(relay_id=relay_id, state=action.state, source="auto", device_id=device_id)
    return actions


def main(pause=sleep, max_passes: int | None = None) -> None:
    """
    Run the automation loop.

    Args:
        pause (callable): Sleep function (injected in tests).
        max_passes (int | None): Stop after this many passes; None runs forever.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    passes = 0
    while max_passes is None or passes < max_passes:
        passes += 1
        try:
            run_once()
        except Exception:
            log.exception("Automation pass failed")
        pause(POLL_SECONDS)


if __name__ == "__main__":
    main()
