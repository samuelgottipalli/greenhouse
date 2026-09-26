"""
Console listener that prints relay commands seen on MQTT.

Run with ``python getgreenhousedata.py``. Loops until Ctrl+C, printing
``device_id relay_id action_id`` for each message on ``001/#``. Intended as the
start of the Pico -> database ingestion service, which is not built yet.
"""
from pico_functions import subscribe_from_pico

from time import sleep
while True:
    try:
        pico_data = subscribe_from_pico()
        if len(pico_data) > 0:
            print(pico_data["device_id"], pico_data["relay_id"], pico_data["action_id"])
        sleep(1)
    except KeyboardInterrupt:
        break
