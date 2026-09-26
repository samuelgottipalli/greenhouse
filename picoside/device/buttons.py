"""
Push buttons for the greenhouse controller.

Five buttons with internal pull-ups (pressed = pin reads 0), triggering on the
falling edge. Button 0 is the screen button; buttons 1-4 are the relay
buttons. The interrupt handlers only debounce and record ``(button, ticks)``
events; ``controller.Controller`` interprets them in the main loop, so no
slow work or LCD access ever happens inside an interrupt.
"""
import time

import machine

TOGGLE = 0
MAX_EVENTS = 16


class Buttons:
    """
    Records debounced button presses for the main loop.

    Attributes:
        pins (list[machine.Pin]): Screen button, then relay buttons 1-4.
        events (list[tuple[int, int]]): Presses not yet taken by the loop.
    """

    def __init__(self, config, debounce_ms=50):
        """
        Configure the button pins and register their interrupts.

        Args:
            config (dict): Uses ``button_toggle_pin`` and ``button_relay_pins``.
            debounce_ms (int): Ignore edges closer together than this.
        """
        pin_numbers = [config["button_toggle_pin"]] + list(config["button_relay_pins"])
        self.pins = [machine.Pin(n, machine.Pin.IN, machine.Pin.PULL_UP) for n in pin_numbers]
        self.events = []
        self._debounce_ms = debounce_ms
        self._last = [None] * len(self.pins)
        for index, pin in enumerate(self.pins):
            pin.irq(trigger=machine.Pin.IRQ_FALLING, handler=self._make_handler(index))

    def _make_handler(self, index):
        """
        Build the interrupt handler for one button.

        Args:
            index (int): Button index (0 = screen, 1-4 = relay buttons).

        Returns:
            callable: Handler taking the pin.
        """
        def handler(_pin):
            now = time.ticks_ms()
            last = self._last[index]
            if last is not None and time.ticks_diff(now, last) < self._debounce_ms:
                return
            self._last[index] = now
            if len(self.events) < MAX_EVENTS:
                self.events.append((index, now))

        return handler

    def take_events(self):
        """
        Return and clear the recorded presses, oldest first.

        Returns:
            list[tuple[int, int]]: ``(button index, ticks_ms at press)``.
        """
        events, self.events = self.events, []
        return events

    def is_pressed(self, index):
        """
        Tell whether a button is being held down right now.

        Args:
            index (int): Button index.

        Returns:
            bool: True while pressed.
        """
        return self.pins[index].value() == 0
