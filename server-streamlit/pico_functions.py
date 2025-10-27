"""
This module publishes data to pico W device via MQTT.
"""
from os import getenv
from typing import Literal

import local_utils as lu
from paho.mqtt.publish import single
from paho.mqtt.subscribe import simple
from paho.mqtt.properties import MQTTException
import json

lu.get_config()


def publish_relay_status(device_id:str, relay_id:str, action_id:str) -> None | Literal[True]:
    """
    Publish a message to the MQTT broker.
    This message is to be sent to the Pico W device to control the relays.

    Args:
        device_id (str): Device id of the Pico W device.
        relay_id (str): Relay id to control.
        action_id (str): Action id to perform.

    Returns:
        None | Literal[True]: If the message was published successfully, returns True. Otherwise, returns None.
    """
    hostname: str | None = getenv(key="MQTT_HOST", default="localhost")
    port: int | None = int(getenv(key="MQTT_PORT", default='1883'))
    try:
        payload = {'device_id':device_id, 'relay_id':relay_id, 'action_id':action_id}
        payload = str(payload).replace("'", '"')
        single(
            topic=f"{device_id}/{relay_id}",
            payload=payload,
            hostname=hostname,
            port=port,
            # retain=True,
            client_id=device_id,
            # keepalive=5,
        )
        return True
    except (MQTTException, OSError, ValueError) as e:
        print(e)
        return None


def subscribe_from_pico() -> dict[str, float | None]:
    """
    Subscribe to the MQTT broker.
    
    Returns:
        dict[str, float | None]: Dictionary of values recorded from the Pico W device.
    """
    hostname: str = getenv(key="MQTT_HOST", default="localhost")
    port: int = int(getenv(key="MQTT_PORT", default='1883'))
    device_id = "001"

    msg1 = simple(topics=f"{device_id}/#", hostname=hostname, port=port)
    if msg1 is not None and getattr(msg1, "payload", None) is not None:
        return json.loads(msg1.payload.decode('utf-8'))
    else:
        return {}