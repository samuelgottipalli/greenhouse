"""
This module publishes data to pico W device via MQTT.
"""
from os import getenv
from typing import Literal

import local_utils as lu
from paho.mqtt.publish import single
from paho.mqtt.subscribe import simple
from paho.mqtt.properties import MQTTException


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
            keepalive=5,
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

    def _get_topic_value(topic: str) -> float | None:
        msg = simple(topic, hostname=hostname, port=port, retained=True, msg_count=2)
        if not msg or getattr(msg, "payload", None) is None:
            return msg.payload
        try:
            payload = msg.payload
            # If payload is bytes, decode; otherwise convert to string
            if isinstance(payload, bytes):
                text = payload.decode()
            else:
                text = str(payload)
            return round(float(text), 2)
        except (UnicodeDecodeError, ValueError, TypeError, AttributeError):
            return msg.payload

    msg1 = simple("001/1", hostname=hostname)
    if msg1 is not None and getattr(msg1, "payload", None) is not None:
        print(msg1.topic, msg1.payload)
    msg2 = simple("001/2", hostname=hostname)
    if msg2 is not None and getattr(msg2, "payload", None) is not None:
        print(msg2.topic, msg2.payload)
    msg3 = simple("001/3", hostname=hostname)
    if msg3 is not None and getattr(msg3, "payload", None) is not None:
        print(msg3.topic, msg3.payload)
    msg4 = simple("001/4", hostname=hostname)
    if msg4 is not None and getattr(msg4, "payload", None) is not None:
        print(msg4.topic, msg4.payload)
    # pico_temp = _get_topic_value("#")
    # pico_temp = _get_topic_value("001/002")
    # pico_humidity = _get_topic_value("001/008")
    # pico_light = _get_topic_value("001/006")
    # return pico_temp
    # return {"pico_temp": pico_temp, "pico_humidity": pico_humidity, "pico_light": pico_light}
