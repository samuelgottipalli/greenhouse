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
