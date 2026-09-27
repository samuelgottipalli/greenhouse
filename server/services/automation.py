"""
Background automation service.

Run from the ``server/`` folder with ``python -m services.automation``. Every
``POLL_SECONDS`` it loads the current thresholds, watering schedule, latest
sensor readings and latest relay states, asks ``core.automation.decide`` what
to change, and for each change publishes an MQTT command and logs a relay
event with source ``"auto"``. It also keeps the controller's copy of the
settings current (retained ``settings`` topic) for the controller's local
mode, and stands back while the controller reports offline. The rules themselves (hysteresis, stale-data
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
from core.automation import Reading, RelayState, decide, device_settings
from core.health import Heartbeat
from core.mqtt import publish_device_settings, publish_relay_command
from core.timeutil import parse_utc_timestamp

log = logging.getLogger(__name__)

POLL_SECONDS = 5

# Last settings payload the broker accepted, per device (published when it changes).
_published_settings: dict[int, dict] = {}


def sync_device_settings(limits, slots, device_id: int) -> bool:
    """
    Publish the controller's local-mode settings if they changed.

    Args:
        limits (dict): Threshold name to ``(value, buffer)``.
        slots (list): Watering slots.
        device_id (int): Device.

    Returns:
        bool: True if a new copy was published.
    """
    payload = device_settings(limits, slots)
    if _published_settings.get(device_id) == payload:
        return False
    if publish_device_settings(payload, device_id=device_id):
        _published_settings[device_id] = payload
        log.info("Published settings for device %s", device_id)
        return True
    return False


def device_is_online(device_id: int) -> bool:
    """
    Tell whether the controller can receive commands.

    Returns:
        bool: False only if it last reported offline (unknown counts as online).
    """
    status = db.device_status(device_id=device_id)
    return status is None or status["status"] == "online"


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
        list[Action]: The changes sent to the broker (empty if nothing to do,
        inputs are missing or the broker is unreachable). Only these are logged.
    """
    inputs = load_inputs(device_id)
    if inputs is None:
        log.warning("Settings or relays missing; run `python -m scripts.upgrade_db`")
        return []
    limits, slots, readings, states, relay_ids = inputs
    sync_device_settings(limits, slots, device_id)
    now = now or datetime.now(timezone.utc)
    online = device_is_online(device_id)
    if not online:
        log.info("Controller %s offline: its local mode is in charge", device_id)
    actions = decide(limits, slots, readings, states, now, ZoneInfo(settings.TIMEZONE), online)
    sent = []
    for action in actions:
        relay_id = relay_ids[action.relay]
        if not publish_relay_command(relay_id=relay_id, state=action.state, source="auto", device_id=device_id):
            # Not sent: log nothing, so the next pass tries again (S-19).
            log.error("Could not publish %s %s; will retry", action.relay, action.state)
            continue
        log.info("Switched %s %s: %s", action.relay, "on" if action.state else "off", action.reason)
        db.log_relay_event(relay_id=relay_id, state=action.state, source="auto", device_id=device_id)
        sent.append(action)
    return sent


def main(pause=sleep, max_passes: int | None = None, heartbeat: Heartbeat | None = None) -> None:
    """
    Run the automation loop.

    Each pass automates every registered device. A heartbeat is recorded
    after each pass that completes; a pass that
    raises does not beat, so repeated failures show as "down" and the
    systemd watchdog restarts the service.

    Args:
        pause (callable): Sleep function (injected in tests).
        max_passes (int | None): Stop after this many passes; None runs forever.
        heartbeat (Heartbeat | None): Defaults to ``Heartbeat("automation")``.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    heartbeat = heartbeat or Heartbeat("automation")
    passes = 0
    while max_passes is None or passes < max_passes:
        passes += 1
        try:
            devices = db.list_devices() or {}
            sent = [action for device_id in devices for action in run_once(device_id=device_id)]
        except Exception:
            log.exception("Automation pass failed")
        else:
            heartbeat.beat(True, f"{len(devices)} devices, {len(sent)} changes last pass")
        pause(POLL_SECONDS)


if __name__ == "__main__":
    main()
