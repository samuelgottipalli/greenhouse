"""
MQTT messages from the server to the greenhouse controller.

Topics and payloads are described in ``docs/MQTT.md``. Relay commands go to
``<prefix>/<device_id>/relay/set`` as ``{"relay": n, "state": 0|1, "source": ...}``.
Broker settings (host, port, optional username/password, topic prefix) come
from ``core.settings``.
"""
import json
import logging

from paho.mqtt.publish import single

from core import settings

log = logging.getLogger(__name__)


def device_topic(device_id: int, suffix: str) -> str:
    """
    Build a per-device topic.

    Args:
        device_id (int): Device ID.
        suffix (str): Topic below the device, e.g. ``"relay/set"``.

    Returns:
        str: e.g. ``"greenhouse/1/relay/set"``.
    """
    return f"{settings.MQTT_TOPIC_PREFIX}/{device_id}/{suffix}"


def publish_device_settings(settings_payload: dict, device_id: int = settings.DEVICE_ID) -> bool:
    """
    Publish the automation settings the controller uses in local mode.

    Sent retained to ``<prefix>/<device_id>/settings``, so the controller gets
    the latest copy whenever it connects (see docs/MQTT.md).

    Args:
        settings_payload (dict): Output of ``core.automation.device_settings``.
        device_id (int): Target device.

    Returns:
        bool: True if the broker accepted the message.
    """
    auth = None
    if settings.MQTT_USERNAME:
        auth = {"username": settings.MQTT_USERNAME, "password": settings.MQTT_PASSWORD}
    try:
        single(
            topic=device_topic(device_id, "settings"),
            payload=json.dumps(settings_payload, sort_keys=True),
            qos=1,
            retain=True,
            hostname=settings.MQTT_HOST,
            port=settings.MQTT_PORT,
            auth=auth,
        )
    except (OSError, ValueError) as err:
        log.error("Could not publish device settings: %s", err)
        return False
    return True


def publish_relay_command(
    relay_id: int,
    state: int,
    source: str,
    device_id: int = settings.DEVICE_ID,
) -> bool:
    """
    Ask the controller to switch a relay on or off.

    Args:
        relay_id (int): Relay number, 1-8.
        state (int): 1 for on, 0 for off.
        source (str): Who is asking, ``"web"`` or ``"auto"``; echoed back by the
            device in its state message.
        device_id (int): Target device.

    Returns:
        bool: True if the broker accepted the message, False if it could not be
        sent (broker unreachable, bad credentials, ...).
    """
    auth = None
    if settings.MQTT_USERNAME:
        auth = {"username": settings.MQTT_USERNAME, "password": settings.MQTT_PASSWORD}
    payload = json.dumps({"relay": int(relay_id), "state": int(state), "source": source})
    try:
        single(
            topic=device_topic(device_id, "relay/set"),
            payload=payload,
            qos=1,
            hostname=settings.MQTT_HOST,
            port=settings.MQTT_PORT,
            auth=auth,
        )
    except (OSError, ValueError) as err:
        log.error("Could not publish relay command: %s", err)
        return False
    return True
