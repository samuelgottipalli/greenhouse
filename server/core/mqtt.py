"""
MQTT messages from the server to the greenhouse controller.

Topics and payloads are described in ``docs/MQTT.md``. Relay commands go to
``<prefix>/<device_id>/relay/set`` as ``{"relay": n, "state": 0|1, "source": ...}``.
Broker settings (host, port, optional username/password, TLS, topic prefix)
come from ``core.settings``; :func:`connection` and :func:`configure_client`
apply them, so every connection the server makes (here, ``core/firmware.py``,
``services/ingest.py``) logs in and encrypts the same way.
"""
import json
import logging

from paho.mqtt.publish import single

from core import settings

log = logging.getLogger(__name__)


def auth() -> dict | None:
    """The broker login for paho's ``single()``, or None when the broker has no logins."""
    if settings.MQTT_USERNAME:
        return {"username": settings.MQTT_USERNAME, "password": settings.MQTT_PASSWORD}
    return None


def tls() -> dict | None:
    """
    TLS settings for paho, or None for a plain connection.

    Returns:
        dict | None: ``{"ca_certs": MQTT_CA_FILE}``; None (the default)
        means the system's trusted roots, which cover the hosted services.
    """
    return {"ca_certs": settings.MQTT_CA_FILE} if settings.MQTT_TLS else None


def connection() -> dict:
    """
    Keyword arguments for paho's ``single()``: address, login and TLS.

    Returns:
        dict: ``hostname``, ``port``, ``auth`` and ``tls``.
    """
    return {"hostname": settings.MQTT_HOST, "port": settings.MQTT_PORT, "auth": auth(), "tls": tls()}


def configure_client(client) -> None:
    """
    Give a long-lived paho client the broker login and TLS settings.

    Args:
        client (paho.mqtt.client.Client): Not yet connected.
    """
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
    if settings.MQTT_TLS:
        client.tls_set(ca_certs=settings.MQTT_CA_FILE)


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
    try:
        single(
            topic=device_topic(device_id, "settings"),
            payload=json.dumps(settings_payload, sort_keys=True),
            qos=1,
            retain=True,
            **connection(),
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
    payload = json.dumps({"relay": int(relay_id), "state": int(state), "source": source})
    try:
        single(
            topic=device_topic(device_id, "relay/set"),
            payload=payload,
            qos=1,
            **connection(),
        )
    except (OSError, ValueError) as err:
        log.error("Could not publish relay command: %s", err)
        return False
    return True


def publish_controller_restart(device_id: int = settings.DEVICE_ID) -> bool:
    """
    Ask a controller to restart (Settings › System). Controllers from 1.3.0
    understand it; older ones ignore it.

    Sent on the controller's command topic (``relay/set``), which its broker
    login may already read, as ``{"action": "restart"}``.

    Args:
        device_id (int): Target device.

    Returns:
        bool: True if the broker accepted the message.
    """
    try:
        single(
            topic=device_topic(device_id, "relay/set"),
            payload=json.dumps({"action": "restart", "source": "web"}),
            qos=1,
            **connection(),
        )
    except (OSError, ValueError) as err:
        log.error("Could not send the restart: %s", err)
        return False
    return True
