"""
Background service that stores what the greenhouse controllers publish.

Run from the ``server/`` folder with ``python -m services.ingest``. It
subscribes to the device topics in docs/MQTT.md and writes:

* ``<prefix>/<device>/telemetry`` -> ``sensor_readings`` (temperature,
  humidity, raw light), using the device's ``ts_utc`` or, when the device
  clock is not set, the time the message arrived. Replayed readings are
  ignored.
* ``<prefix>/<device>/relay/<n>/state`` -> ``relay_events``, only when the
  state differs from the last logged one (so echoes of web/automation
  commands and retained repeats are not duplicated).
* ``<prefix>/<device>/status`` -> ``device_status`` (online/offline).
* ``<prefix>/<device>/firmware`` -> ``device_status`` (installed version and
  over-the-air update progress).
  Telemetry also updates the device's health there (last seen, uptime, free
  memory, Wi-Fi signal).

The MQTT client reconnects on its own (1-60 s backoff).
"""
import json
import logging
from time import sleep

from paho.mqtt.client import CallbackAPIVersion, Client

from core import db, settings
from core.health import Heartbeat
from core.timeutil import parse_utc_timestamp, utc_timestamp

log = logging.getLogger(__name__)

# Telemetry field -> measure name in the measures table.
TELEMETRY_MEASURES: dict[str, str] = {
    "temperature_c": "temperature",
    "humidity_pct": "humidity",
    "light_raw": "light_raw",
}
SOURCES = ("auto", "web", "device")
WATCH_SECONDS = 10


def subscriptions(prefix: str = settings.MQTT_TOPIC_PREFIX) -> list[str]:
    """
    Topic filters the service subscribes to.

    Args:
        prefix (str): Topic prefix.

    Returns:
        list[str]: Filters for telemetry, relay state, status and firmware of all devices.
    """
    return [f"{prefix}/+/telemetry", f"{prefix}/+/relay/+/state", f"{prefix}/+/status", f"{prefix}/+/firmware"]


def valid_timestamp(value) -> str | None:
    """
    Accept a device timestamp only if it is in the storage format.

    Args:
        value: ``ts_utc`` from a payload (may be None or malformed).

    Returns:
        str | None: The timestamp, or None if unusable.
    """
    if not isinstance(value, str):
        return None
    try:
        parse_utc_timestamp(value)
    except ValueError:
        return None
    return value


def _int_or_none(value) -> int | None:
    """Return an integer health value from a payload, or None if absent or not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def handle_message(topic: str, payload: bytes, received_utc: str,
                   prefix: str = settings.MQTT_TOPIC_PREFIX) -> str:
    """
    Store one MQTT message.

    Args:
        topic (str): Topic it arrived on.
        payload (bytes): Message body.
        received_utc (str): Arrival time, ``YYYY-MM-DD HH:MM:SS`` UTC.
        prefix (str): Topic prefix.

    Returns:
        str: What happened, for the log (never raises for bad input).
    """
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != prefix or not parts[1].isdigit():
        return f"ignored topic {topic}"
    device_id = int(parts[1])
    rest = parts[2:]

    if rest == ["status"]:
        status = payload.decode("utf-8", "replace").strip()
        if status not in ("online", "offline"):
            return f"ignored status {status!r}"
        ok = db.set_device_status(status, received_utc, device_id=device_id)
        return f"device {device_id} {status}" if ok else "status not stored"

    try:
        data = json.loads(payload)
    except ValueError:
        return f"ignored non-JSON message on {topic}"
    if not isinstance(data, dict):
        return f"ignored non-object message on {topic}"
    at = valid_timestamp(data.get("ts_utc")) or received_utc

    if rest == ["telemetry"]:
        values = {
            measure: data[field] for field, measure in TELEMETRY_MEASURES.items()
            if isinstance(data.get(field), (int, float)) and not isinstance(data.get(field), bool)
        }
        stored = db.insert_sensor_readings(values, at, device_id=device_id)
        db.update_device_health(
            device_id, received_utc,
            uptime_s=_int_or_none(data.get("uptime_s")),
            mem_free=_int_or_none(data.get("mem_free")),
            rssi_dbm=_int_or_none(data.get("rssi_dbm")),
        )
        return f"telemetry from {device_id}: {stored} new readings"

    if rest == ["firmware"]:
        version, state = data.get("version"), data.get("state")
        if not isinstance(version, str) or not version or state not in db.FIRMWARE_STATES:
            return f"ignored bad firmware report from {device_id}"
        detail = data.get("detail") if isinstance(data.get("detail"), str) else ""
        db.update_firmware_status(device_id, version[:40], state, detail[:200], received_utc)
        return f"firmware of {device_id}: {version} {state}"

    if len(rest) == 3 and rest[0] == "relay" and rest[2] == "state" and rest[1].isdigit():
        state = data.get("state")
        if state not in (0, 1) or isinstance(state, bool):
            return f"ignored bad state {state!r}"
        source = data.get("source") if data.get("source") in SOURCES else "device"
        logged = db.record_relay_state(int(rest[1]), state, source, at, device_id=device_id)
        return f"relay {rest[1]} of {device_id} -> {state}: {'logged' if logged else 'unchanged'}"

    return f"ignored topic {topic}"


def make_client() -> Client:
    """
    Build the MQTT client with credentials, callbacks and reconnect backoff.

    Returns:
        Client: Configured, not yet connected.
    """
    client = Client(CallbackAPIVersion.VERSION2, client_id="greenhouse-ingest")
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
    client.reconnect_delay_set(min_delay=1, max_delay=60)

    def on_connect(client, _userdata, _flags, reason_code, _properties):
        log.info("Connected to %s:%s (%s)", settings.MQTT_HOST, settings.MQTT_PORT, reason_code)
        for topic in subscriptions():
            client.subscribe(topic, qos=1)

    def on_message(_client, _userdata, message):
        try:
            log.info(handle_message(message.topic, message.payload, utc_timestamp()))
        except Exception:
            log.exception("Failed to handle message on %s", message.topic)

    client.on_connect = on_connect
    client.on_message = on_message
    return client


def main() -> None:
    """Connect (retrying until the broker is reachable) and process messages forever."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = make_client()
    client.connect_async(settings.MQTT_HOST, settings.MQTT_PORT, keepalive=60)
    client.loop_start()
    watch(client, Heartbeat("ingest"))


def watch(client: Client, heartbeat: "Heartbeat", pause=sleep, max_passes: int | None = None) -> None:
    """
    Keep the service's heartbeat going while the MQTT network thread runs.

    Healthy means connected to the broker. If the network thread dies the
    heartbeat stops, and the systemd watchdog restarts the service.

    Args:
        client (Client): Started MQTT client.
        heartbeat (Heartbeat): This service's heartbeat.
        pause (callable): Sleep function (injected in tests).
        max_passes (int | None): Stop after this many passes; None runs forever.
    """
    passes = 0
    while max_passes is None or passes < max_passes:
        passes += 1
        thread = getattr(client, "_thread", None)
        if thread is not None and not thread.is_alive():
            log.error("MQTT network thread stopped")
            return
        connected = client.is_connected()
        heartbeat.beat(connected, "connected" if connected else "broker unreachable")
        pause(WATCH_SECONDS)


if __name__ == "__main__":
    main()
