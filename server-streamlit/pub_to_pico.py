"""
This module publishes data to pico W device via MQTT.
"""
import os
from typing import Literal

import local_utils as lu
from paho.mqtt.publish import single

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
    hostname: str | None = os.getenv(key="MQTT_HOST")
    try:
        port: int | None = int(os.getenv(key="MQTT_PORT"))
    except ValueError:
        port: int | None = None
    if not hostname or not port:
        print("Missing environment variables. Check .env file.")
        return None
    try:
        payload = {'device_id':device_id, 'relay_id':relay_id, 'action_id':action_id}
        payload = str(payload).replace("'", '"')
        single(
            topic=f"{device_id}/{relay_id}",
            payload=payload,
            hostname=hostname,
            port=port,
            retain=True,
            client_id=device_id,
            keepalive=60,
        )
        return True
    except Exception as e:
        print(e)


# publish("001", "1", "021")
