"""
Relay bank driver for the greenhouse controller.

Drives the 8-channel relay board. Relay numbers are 1-based everywhere, to
match the board labels. Default wiring: 1 water, 2 fan, 3 heater, 4 light,
5-8 spare (names come from ``relay_names`` in config). All relays are switched
off at boot. Set ``relay_active_low`` for boards that switch on when the pin
is low.
"""
import machine

COUNT = 8


class Relays:
    """
    Holds the on/off state of each relay and drives its pin.

    Attributes:
        pins (list[machine.Pin]): Output pins for relays 1-8.
        names (list[str]): Relay names for the LCD.
    """

    def __init__(self, config):
        """
        Configure the relay pins as outputs, all off.

        Args:
            config (dict): Uses ``relay_pins``, ``relay_active_low`` and
                ``relay_names``.
        """
        self.pins = [machine.Pin(pin, machine.Pin.OUT) for pin in config["relay_pins"]]
        self.names = config["relay_names"]
        self._active_low = config["relay_active_low"]
        self._states = [0] * COUNT
        for number in range(1, COUNT + 1):
            self._drive(number)

    @staticmethod
    def valid(number):
        """
        Tell whether a value is a relay number.

        Args:
            number (object): Value to check.

        Returns:
            bool: True for the integers 1-8.
        """
        return isinstance(number, int) and not isinstance(number, bool) and 1 <= number <= COUNT

    def _drive(self, number):
        """Write a relay's state to its pin."""
        on = self._states[number - 1]
        if self._active_low:
            on = 0 if on else 1
        self.pins[number - 1].value(on)

    def set(self, number, state):
        """
        Switch a relay on or off.

        Args:
            number (int): Relay number, 1-8.
            state (int | bool): Truthy for on.

        Returns:
            bool: True if the state changed.
        """
        state = 1 if state else 0
        changed = self._states[number - 1] != state
        self._states[number - 1] = state
        self._drive(number)
        return changed

    def toggle(self, number):
        """
        Flip a relay.

        Args:
            number (int): Relay number, 1-8.

        Returns:
            int: The new state (1 on, 0 off).
        """
        self.set(number, not self._states[number - 1])
        return self._states[number - 1]

    def state(self, number):
        """
        Return a relay's state.

        Args:
            number (int): Relay number, 1-8.

        Returns:
            int: 1 on, 0 off.
        """
        return self._states[number - 1]

    def states(self):
        """
        Return every relay's state.

        Returns:
            list[int]: States of relays 1-8.
        """
        return list(self._states)

    def name(self, number):
        """
        Return a relay's name.

        Args:
            number (int): Relay number, 1-8.

        Returns:
            str: Name from config, e.g. ``"fan"``.
        """
        return self.names[number - 1]
