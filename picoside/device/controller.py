"""
Main-loop logic for the greenhouse controller.

``main.py`` builds the hardware objects, calls :meth:`Controller.start` once,
then :meth:`Controller.tick` every ``loop_ms``. Each tick is short and never
blocks for long:

1. Track uptime (wrap-safe, using ``ticks_diff``).
2. Handle button presses recorded by the interrupt handlers.
3. Let the network reconnect, receive commands and flush queued messages.
4. Read the sensors every ``sensor_interval_s`` (first read at boot).
5. Publish telemetry every ``publish_interval_s`` (first at boot).
6. Re-sync the clock from NTP every ``ntp_resync_hours`` (retry every 5
   minutes until the first sync succeeds).
7. Redraw the LCD (only lines that changed are written).

Buttons: the screen button cycles main screen -> relay 1..8 -> main; held
together with relay button 1 it shows the IP address. A relay button toggles
its relay (1-4); pressing it twice within ``DOUBLE_PRESS_MS`` toggles the paired
spare relay (5-8) instead. Non-main screens return to main after 10 s.

Every relay change, whatever its source, is published as a retained state
message so the server's view stays in step.
"""
import time

from clock import format_uptime

SCREEN_MAIN = 0
SCREEN_IP = 9
RELAY_SCREENS = 8
SCREEN_TIMEOUT_MS = 10000
DOUBLE_PRESS_MS = 400
NTP_RETRY_MS = 5 * 60 * 1000
TOGGLE_BUTTON = 0
PAIRED_RELAY = {1: 5, 2: 6, 3: 7, 4: 8}
COMMAND_SOURCES = ("web", "auto")


class Controller:
    """
    Ties sensors, relays, buttons, display, network and clock together.

    Attributes:
        screen (int): 0 main, 1-8 relay status, 9 IP address.
        temperature (float | None): Last DHT22 temperature in °C.
        humidity (float | None): Last DHT22 relative humidity in %.
        light (int | None): Last raw LDR reading.
        uptime_ms (int): Milliseconds since :meth:`start`.
    """

    def __init__(self, config, display, sensors, relays, buttons, net, clock):
        """
        Args:
            config (dict): Parsed config (intervals, ``device_id``).
            display (display.Display): The LCD.
            sensors (sensors.Sensors): DHT22 and LDR.
            relays (relays.Relays): Relay bank.
            buttons (buttons.Buttons): Button event source.
            net (net.Network): Wi-Fi/MQTT link; its ``on_command`` is set here.
            clock (clock.Clock): UTC/local time and NTP.
        """
        self.config = config
        self.display = display
        self.sensors = sensors
        self.relays = relays
        self.buttons = buttons
        self.net = net
        self.clock = clock
        net.on_command = self.handle_command

        self.screen = SCREEN_MAIN
        self.screen_since = 0
        self.pending = {}
        self.temperature = None
        self.humidity = None
        self.light = None
        self.uptime_ms = 0
        self._last_tick = None
        self._last_sensor = None
        self._last_publish = None
        self._last_ntp = None
        self._sensor_ms = config["sensor_interval_s"] * 1000
        self._publish_ms = config["publish_interval_s"] * 1000
        self._ntp_ms = config["ntp_resync_hours"] * 3600 * 1000

    # --- lifecycle ------------------------------------------------------

    def start(self):
        """
        Boot sequence: Wi-Fi (bounded wait), NTP, MQTT, then clear the screen.

        Each step reports progress on the LCD; failures are left for
        :meth:`tick` to retry.
        """
        self.display.show_message("Connecting to WiFi...")
        if self.net.connect_wifi():
            self.display.show_message("WiFi connected. Syncing clock...")
            if self.clock.sync():
                self._last_ntp = time.ticks_ms()
            self.display.show_message("Connecting to MQTT...")
            if not self.net.connect_mqtt():
                self.display.show_message("MQTT unavailable, will retry.")
        else:
            self.display.show_message("WiFi unavailable, will retry.")
        self._last_tick = time.ticks_ms()
        self.display.clear()

    def tick(self):
        """Run one pass of the main loop (see module docstring)."""
        now = time.ticks_ms()
        if self._last_tick is None:
            self._last_tick = now
        self.uptime_ms += time.ticks_diff(now, self._last_tick)
        self._last_tick = now

        self.handle_buttons(now)
        self.net.poll(now)
        if self._due(self._last_sensor, self._sensor_ms, now):
            self.read_sensors()
            self._last_sensor = now
        if self._due(self._last_publish, self._publish_ms, now):
            self.publish_telemetry()
            self._last_publish = now
        self._maybe_sync_clock(now)
        if self.screen != SCREEN_MAIN and time.ticks_diff(now, self.screen_since) > SCREEN_TIMEOUT_MS:
            self.screen = SCREEN_MAIN
        self.display.show_lines(self.screen_lines())

    @staticmethod
    def _due(last, interval_ms, now):
        """Tell whether a periodic job should run."""
        return last is None or time.ticks_diff(now, last) >= interval_ms

    def _maybe_sync_clock(self, now):
        """Re-sync NTP when due; retry sooner while it has never succeeded."""
        interval = self._ntp_ms if self.clock.synced else NTP_RETRY_MS
        if self.net.wifi_ok and self._due(self._last_ntp, interval, now):
            self.clock.sync()
            self._last_ntp = now

    # --- sensors and telemetry -------------------------------------------

    def read_sensors(self):
        """Read the DHT22 and LDR; keep the last good DHT values on failure."""
        temperature, humidity = self.sensors.read_dht()
        if temperature is not None:
            self.temperature, self.humidity = temperature, humidity
        self.light = self.sensors.read_ldr()

    def publish_telemetry(self):
        """Publish (or queue) a sensor and relay snapshot."""
        self.net.publish("telemetry", {
            "device_id": self.config["device_id"],
            "ts_utc": self.clock.utc_str(),
            "temperature_c": self.temperature,
            "humidity_pct": self.humidity,
            "light_raw": self.light,
            "relays": self.relays.states(),
            "uptime_s": self.uptime_ms // 1000,
        })

    # --- relays ----------------------------------------------------------

    def switch_relay(self, number, state, source, now=None):
        """
        Set a relay, publish its new state and show its status screen.

        Args:
            number (int): Relay number, 1-8.
            state (int): 1 on, 0 off.
            source (str): ``"device"``, ``"web"`` or ``"auto"``.
            now (int | None): ``ticks_ms`` now.
        """
        self.relays.set(number, state)
        self.net.publish("relay/{}/state".format(number), {
            "device_id": self.config["device_id"],
            "relay": number,
            "state": self.relays.state(number),
            "source": source,
            "ts_utc": self.clock.utc_str(),
        }, retain=True)
        self.show_screen(number, time.ticks_ms() if now is None else now)

    def handle_command(self, command):
        """
        Apply a relay command received over MQTT.

        Args:
            command (dict): ``{"relay": 1-8, "state": 0|1, "source": "web"|"auto"}``;
                ``source`` is optional. Invalid commands are ignored.

        Returns:
            bool: True if the command was applied.
        """
        number = command.get("relay")
        state = command.get("state")
        if not self.relays.valid(number) or state not in (0, 1) or isinstance(state, bool):
            print("Ignoring invalid command:", command)
            return False
        source = command.get("source")
        self.switch_relay(number, state, source if source in COMMAND_SOURCES else "web")
        return True

    # --- buttons and screens ---------------------------------------------

    def show_screen(self, screen, now):
        """
        Switch the LCD to a screen and restart its timeout.

        Args:
            screen (int): 0 main, 1-8 relay, 9 IP address.
            now (int): ``ticks_ms`` now.
        """
        self.screen = screen
        self.screen_since = now

    def handle_buttons(self, now):
        """
        Interpret recorded button presses and resolve single presses.

        A relay-button press waits ``DOUBLE_PRESS_MS`` for a second press, and
        is only acted on once the button is released (so a held button 1 can
        be combined with the screen button).

        Args:
            now (int): ``ticks_ms`` now.
        """
        for index, at in self.buttons.take_events():
            if index == TOGGLE_BUTTON:
                if self.buttons.is_pressed(1):
                    self.pending.pop(1, None)
                    self.show_screen(SCREEN_IP, now)
                else:
                    following = self.screen + 1 if self.screen < RELAY_SCREENS else SCREEN_MAIN
                    self.show_screen(following, now)
                continue
            first = self.pending.pop(index, None)
            if first is not None and time.ticks_diff(at, first) <= DOUBLE_PRESS_MS:
                self.toggle_from_button(PAIRED_RELAY[index], now)
                continue
            if first is not None:
                self.toggle_from_button(index, now)
            self.pending[index] = at
        for index in list(self.pending):
            waited = time.ticks_diff(now, self.pending[index])
            if waited > DOUBLE_PRESS_MS and not self.buttons.is_pressed(index):
                del self.pending[index]
                self.toggle_from_button(index, now)

    def toggle_from_button(self, number, now):
        """
        Flip a relay because a button was pressed.

        Args:
            number (int): Relay number, 1-8.
            now (int): ``ticks_ms`` now.
        """
        self.switch_relay(number, 0 if self.relays.state(number) else 1, "device", now)

    def network_status(self):
        """
        Summarise connectivity for the LCD.

        Returns:
            str: ``"OK"``, ``"NoMQTT"`` or ``"NoWiFi"``.
        """
        if self.net.mqtt_ok:
            return "OK"
        return "NoMQTT" if self.net.wifi_ok else "NoWiFi"

    def screen_lines(self):
        """
        Build the four LCD lines for the current screen.

        Returns:
            list[str]: Lines of up to 20 characters.
        """
        if self.screen == SCREEN_IP:
            return ["IP address:", self.net.ip_address() or "WiFi not connected", "", ""]
        if 1 <= self.screen <= RELAY_SCREENS:
            return [
                "Relay {}: {}".format(self.screen, self.relays.name(self.screen)),
                "State: {}".format("On" if self.relays.state(self.screen) else "Off"),
                "",
                "",
            ]
        temperature = "--" if self.temperature is None else "{:4.1f}C".format(self.temperature)
        humidity = "--" if self.humidity is None else "{:4.1f}%".format(self.humidity)
        return [
            self.clock.local_str() or "Clock not set",
            "Temp: " + temperature,
            "Hum:  " + humidity,
            "Up {} {}".format(format_uptime(self.uptime_ms / 1000), self.network_status()),
        ]
