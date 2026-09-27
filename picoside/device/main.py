"""
Entry point for the greenhouse controller (Raspberry Pi Pico W, MicroPython).

MicroPython runs ``boot.py`` (update rollback) and then ``main.py`` at every
start. This loads ``config.json``, builds one of each hardware object, runs
the boot sequence and then calls ``Controller.tick()`` every ``loop_ms``
(see ``controller.py`` for what a tick does). A hardware watchdog (on by
default) resets the board if a tick ever hangs; an unexpected error is shown
on the LCD and the board resets after 10 s.

The watchdog starts ``WATCHDOG_DELAY_MS`` after the main loop does. Once
started it can't be stopped, so the delay leaves a window after every
restart in which a computer can stop the program over USB (the installer
and ``mpremote`` do) without the board resetting in the middle of a copy.
While an over-the-air update is on trial the watchdog starts at once.

Setup mode (``provision.py``) runs instead when there are no Wi-Fi or server
settings, when the screen button is held at power-on, or when newly saved
Wi-Fi settings fail on their first boot. It ends by restarting the board.

Over-the-air updates (``ota.py``) never replace this file. It imports the
rest of the code inside the ``try`` below, so even an update that can't be
imported (a syntax error, a missing file) leads to a restart, which
``boot.py`` counts towards rolling the update back.
"""
import time

import machine

WATCHDOG_MS = 8000  # RP2040 maximum is about 8.3 s
WATCHDOG_DELAY_MS = 30000


def run():
    """Build everything, boot, and loop forever."""
    from buttons import Buttons
    from clock import Clock
    from config import config_problems, load_config
    from controller import Controller
    from display import Display
    from net import Network
    from provision import REASON_WIFI_FAILED, button_held, clear_unverified, is_unverified, run_setup, setup_reason
    from relays import Relays
    from sensors import Sensors

    config = load_config()
    display = Display(config)
    screen_button = machine.Pin(config["button_toggle_pin"], machine.Pin.IN, machine.Pin.PULL_UP)
    reason = setup_reason(config, button_held(screen_button, display))
    if reason:
        run_setup(config, display, reason)
        return
    for problem in config_problems(config):
        display.show_message("Config: " + problem)
        time.sleep(2)
    display.show_message("Initializing.. This may take a moment to get all the devices ready!")

    net = Network(config)
    controller = Controller(
        config, display, Sensors(config), Relays(config), Buttons(config), net, Clock(config)
    )
    controller.start()
    if net.wifi_ok:
        clear_unverified()
    elif is_unverified():
        run_setup(config, display, REASON_WIFI_FAILED)
        return

    watchdog = None
    # An update on trial gets the watchdog at once, so a hang counts as a failed start.
    delay = 0 if controller.update_on_trial else WATCHDOG_DELAY_MS
    arm_at = time.ticks_add(time.ticks_ms(), delay)
    while True:
        controller.tick()
        if watchdog:
            watchdog.feed()
        elif config["watchdog"] and time.ticks_diff(time.ticks_ms(), arm_at) >= 0:
            watchdog = machine.WDT(timeout=WATCHDOG_MS)
            net.feed = watchdog.feed
        time.sleep_ms(config["loop_ms"])


try:
    run()
except Exception as err:
    print("Fatal error:", repr(err))
    try:
        from config import load_config
        from display import Display

        Display(load_config()).show_message("Error: " + repr(err))
    except Exception:
        pass
    time.sleep(10)
    machine.reset()
