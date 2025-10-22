from pico_functions import subscribe_from_pico

from time import sleep
while True:
    pico_data = subscribe_from_pico()
    # print(pico_data)
    sleep(5)