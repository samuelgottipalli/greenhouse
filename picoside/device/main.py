"""
Entry point for the greenhouse controller (Raspberry Pi Pico W, MicroPython).

MicroPython runs ``main.py`` at boot. It loads ``config.json``, builds one of
each hardware object, runs the boot sequence and then calls
``Controller.tick()`` every ``loop_ms`` (see ``controller.py`` for what a tick
does). A hardware watchdog (on by default) resets the board if a tick ever
hangs; an unexpected error is shown on the LCD and the board resets after 10 s.
"""
import time

import machine

from buttons import Buttons
from clock import Clock
from config import config_problems, load_config
from controller import Controller
from display import Display
from net import Network
from relays import Relays
from sensors import Sensors

WATCHDOG_MS = 8000  # RP2040 maximum is about 8.3 s


def run():
    """Build everything, boot, and loop forever."""
    config = load_config()
    display = Display(config)
    for problem in config_problems(config):
        display.show_message("Config: " + problem)
        time.sleep(2)
    display.show_message("Initializing.. This may take a moment to get all the devices ready!")

    net = Network(config)
    controller = Controller(
        config, display, Sensors(config), Relays(config), Buttons(config), net, Clock(config)
    )
    controller.start()

    watchdog = machine.WDT(timeout=WATCHDOG_MS) if config["watchdog"] else None
    if watchdog:
        net.feed = watchdog.feed
    while True:
        controller.tick()
        if watchdog:
            watchdog.feed()
        time.sleep_ms(config["loop_ms"])


try:
    run()
except Exception as err:
    print("Fatal error:", repr(err))
    try:
        Display(load_config()).show_message("Error: " + repr(err))
    except Exception:
        pass
    time.sleep(10)
    machine.reset()
