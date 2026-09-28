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

Power: the LCD backlight turns off after ``backlight_timeout_s`` without a
button press; the next press only wakes it.

Buttons: the screen button cycles main screen -> relay 1..8 -> main; held
together with relay button 1 it shows the IP address. A relay button toggles
its relay (1-4); pressing it twice within ``DOUBLE_PRESS_MS`` toggles the paired
spare relay (5-8) instead. Non-main screens return to main after 10 s.

Safety and local mode (see ``local_rules.py``):

* If the DHT22 has not given a good reading for 5 minutes, the heater is
  switched off, online or not.
* If the MQTT link has been down for 2 minutes, the controller runs the
  automation rules itself with the last settings the server sent (kept in
  ``settings.json``) and shows ``LOCAL`` on the LCD. Changes are reported as
  ``auto`` once the link is back.
* A controller set up to run on its own (``standalone``, no server) is in
  local mode from the start, with the rules from the setup page (or the
  defaults), and never tries MQTT.

Every relay change, whatever its source, is published as a retained state
message, and all eight states are re-published whenever the MQTT link comes
up (boot or reconnect), so the server's view stays in step.

Updates (see ``ota.py``): an update message is kept and applied on the next
tick (outside the MQTT callback): download, check, swap, restart. Reaching
the broker confirms a new version; one that hasn't after 10 minutes restarts
the board so ``boot.py`` can count the failed start. The installed version
and how the last update went are published on ``firmware`` whenever the link
comes up.
"""
import gc
import time

import local_rules
import ota
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
LOCAL_MODE_AFTER_MS = 2 * 60 * 1000
DHT_MAX_AGE_MS = 5 * 60 * 1000


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

    def __init__(self, config, display, sensors, relays, buttons, net, clock, reset=None):
        """
        Args:
            config (dict): Parsed config (intervals, ``device_id``).
            display (display.Display): The LCD.
            sensors (sensors.Sensors): DHT22 and LDR.
            relays (relays.Relays): Relay bank.
            buttons (buttons.Buttons): Button event source.
            net (net.Network): Wi-Fi/MQTT link; its ``on_command`` is set here.
            clock (clock.Clock): UTC/local time and NTP.
            reset (callable | None): Restarts the board (default ``machine.reset``).
        """
        self.config = config
        self.display = display
        self.sensors = sensors
        self.relays = relays
        self.buttons = buttons
        self.net = net
        self.clock = clock
        net.on_command = self.handle_command
        net.on_settings = self.handle_settings
        net.on_firmware = self.handle_firmware
        self.standalone = bool(config.get("standalone"))
        self.settings = local_rules.load_settings()
        if self.settings is None and self.standalone:
            self.settings = local_rules.default_settings()
        self._reset = reset
        self.firmware_request = None
        self.update_on_trial = ota.is_pending()

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
        self._was_online = False
        self._link_down_since = None
        self._last_dht_ok = None
        self._backlight_ms = config["backlight_timeout_s"] * 1000
        self._last_activity = time.ticks_ms()
        self.local_mode = False

    # --- lifecycle ------------------------------------------------------

    def start(self):
        """
        Boot sequence: Wi-Fi (bounded wait), NTP, MQTT, then clear the screen.

        Each step reports progress on the LCD; failures are left for
        :meth:`tick` to retry.
        """
        if self.config["wifi_ssid"]:
            self.display.show_message("Greenhouse v{}. Connecting to WiFi...".format(ota.version_name()))
        if self.net.connect_wifi():
            self.display.show_message("WiFi connected. Syncing clock...")
            if self.clock.sync():
                self._last_ntp = time.ticks_ms()
            if self.standalone:
                self.display.show_message("Running on its own (no server).")
            else:
                self.display.show_message("Connecting to MQTT...")
                if not self.net.connect_mqtt():
                    self.display.show_message("MQTT unavailable, will retry.")
        elif self.config["wifi_ssid"]:
            self.display.show_message("WiFi unavailable, will retry.")
        else:
            self.display.show_message("Running on its own (no server).")
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
        if self.net.mqtt_ok and not self._was_online:
            self.publish_all_states()
            self.report_firmware()
        self._was_online = self.net.mqtt_ok
        if self.firmware_request is not None:
            request, self.firmware_request = self.firmware_request, None
            self.apply_update(request)
        if self.update_on_trial and self.uptime_ms > ota.CONFIRM_WITHIN_MS:
            print("Update not confirmed in time: restarting")
            self.reset()
        was_local = self.local_mode
        self._track_link(now)
        read = self._due(self._last_sensor, self._sensor_ms, now)
        if read:
            self.read_sensors(now)
            self._last_sensor = now
        # Cheap checks, every pass: the heater cut-off must not wait for the
        # next sensor read, and local mode acts as soon as it starts.
        self.apply_safety(now)
        if self.local_mode and (read or not was_local):
            self.apply_local_rules(now)
        if self._due(self._last_publish, self._publish_ms, now):
            self.publish_telemetry()
            self._last_publish = now
        self._maybe_sync_clock(now)
        if self.screen != SCREEN_MAIN and time.ticks_diff(now, self.screen_since) > SCREEN_TIMEOUT_MS:
            self.screen = SCREEN_MAIN
        if self._backlight_ms and self.display.backlight and \
                time.ticks_diff(now, self._last_activity) > self._backlight_ms:
            self.display.set_backlight(False)
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

    def read_sensors(self, now=None):
        """
        Read the DHT22 and LDR; keep the last good DHT values on failure.

        Args:
            now (int | None): ``ticks_ms`` now, recorded for a good DHT read.
        """
        temperature, humidity = self.sensors.read_dht()
        if temperature is not None:
            self.temperature, self.humidity = temperature, humidity
            self._last_dht_ok = time.ticks_ms() if now is None else now
        self.light = self.sensors.read_ldr()

    def dht_fresh(self, now):
        """Tell whether the last good DHT22 reading is recent enough to act on."""
        return self._last_dht_ok is not None and time.ticks_diff(now, self._last_dht_ok) <= DHT_MAX_AGE_MS

    # --- safety and local mode -------------------------------------------

    def _track_link(self, now):
        """Enter local mode after the MQTT link has been down for 2 minutes; leave it when back."""
        if self.standalone:
            self.local_mode = True
            return
        if self.net.mqtt_ok:
            self._link_down_since = None
            self.local_mode = False
            return
        if self._link_down_since is None:
            self._link_down_since = now
        self.local_mode = time.ticks_diff(now, self._link_down_since) >= LOCAL_MODE_AFTER_MS

    def _relay_number(self, name):
        """Find a relay number by its configured name (None if not configured)."""
        for number in range(1, 9):
            if self.relays.name(number) == name:
                return number
        return None

    def apply_safety(self, now):
        """Switch the heater off if the temperature sensor has gone quiet, online or not."""
        heater = self._relay_number("heater")
        if heater and self.relays.state(heater) and not self.dht_fresh(now):
            print("No temperature for 5 minutes: heater off")
            self.switch_relay(heater, 0, "auto", now)

    def apply_local_rules(self, now):
        """Run the automation rules on the device (local mode)."""
        fresh = self.dht_fresh(now)
        states = {}
        for name in ("fan", "heater", "water"):
            number = self._relay_number(name)
            if number:
                states[name] = self.relays.state(number)
        targets = local_rules.decide(
            self.settings,
            self.temperature if fresh else None,
            self.humidity if fresh else None,
            states,
            self.clock.local_minutes(),
        )
        for name, target in targets.items():
            number = self._relay_number(name)
            if number and self.relays.state(number) != target:
                self.switch_relay(number, target, "auto", now)

    def handle_settings(self, payload):
        """
        Keep the automation settings the server publishes, for local mode.

        Args:
            payload (dict): Settings message (see ``local_rules.valid_settings``).

        Returns:
            bool: True if they were new and valid (and saved to flash).
        """
        if not local_rules.valid_settings(payload):
            print("Ignoring invalid settings:", payload)
            return False
        if payload == self.settings:
            return False
        self.settings = payload
        local_rules.save_settings(payload)
        return True

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
            "mem_free": gc.mem_free() if hasattr(gc, "mem_free") else None,
            "rssi_dbm": self.net.rssi(),
        })

    # --- over-the-air updates --------------------------------------------

    def reset(self):
        """Restart the board."""
        if self._reset is None:
            import machine

            self._reset = machine.reset
        self._reset()

    def publish_firmware(self, state, detail=""):
        """
        Publish (or queue) the installed version and update progress, retained.

        Args:
            state (str): ``running``, ``updating``, ``restarting``, ``updated``,
                ``failed`` or ``rolled_back``.
            detail (str): Short explanation for the dashboard.
        """
        self.net.publish("firmware", {
            "device_id": self.config["device_id"],
            "version": ota.current_version(),
            "name": ota.version_name(),
            "state": state,
            "detail": detail,
            "ts_utc": self.clock.utc_str(),
        }, retain=True)

    def report_firmware(self):
        """
        Called when the MQTT link comes up: confirm a version on trial and
        say which version runs and how the last update went.
        """
        if self.update_on_trial:
            ota.confirm()
            self.update_on_trial = False
        result = ota.take_result()
        if result:
            self.publish_firmware(*result)
        else:
            self.publish_firmware("running")

    def handle_firmware(self, manifest):
        """
        Accept an update message; it is applied on the next tick.

        Args:
            manifest (dict): See ``ota.valid_manifest``.

        Returns:
            bool: True if it was accepted.
        """
        if not ota.valid_manifest(manifest):
            print("Ignoring invalid update:", manifest)
            self.publish_firmware("failed", "The update message was not valid")
            return False
        self.firmware_request = manifest
        return True

    def apply_update(self, manifest):
        """
        Download, check and install an update, then restart.

        Relays keep their state while files download; the restart switches
        them off and the server's automation switches them back as needed.

        Args:
            manifest (dict): A valid update message.

        Returns:
            str: ``"current"``, ``"failed"`` or ``"installed"`` (in tests,
            where the reset returns).
        """
        if manifest["version"] == ota.current_version():
            self.publish_firmware("running", "Already up to date")
            return "current"
        self.display.set_backlight(True)
        self.display.show_message("Updating the controller's software. Please wait...")
        self.publish_firmware("updating", "Downloading version " + (manifest.get("name") or manifest["version"]))
        try:
            changed = ota.stage(manifest, feed=self.net.feed)
            if not changed:
                ota.mark_current(manifest["version"])
                self.publish_firmware("running", "Files were already up to date")
                return "current"
            ota.install(manifest, changed)
        except Exception as err:
            print("Update failed:", err)
            self.publish_firmware("failed", str(err)[:120])
            self.display.clear()
            return "failed"
        self.publish_firmware("restarting", "Installed {} files; restarting".format(len(changed)))
        self.display.show_message("Update installed. Restarting...")
        time.sleep_ms(1000)  # let the last messages go out
        self.reset()
        return "installed"

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
        self.publish_state(number, source)
        self.show_screen(number, time.ticks_ms() if now is None else now)

    def publish_state(self, number, source):
        """
        Publish (or queue) one relay's current state as a retained message.

        Args:
            number (int): Relay number, 1-8.
            source (str): ``"device"``, ``"web"`` or ``"auto"``.
        """
        self.net.publish("relay/{}/state".format(number), {
            "device_id": self.config["device_id"],
            "relay": number,
            "state": self.relays.state(number),
            "source": source,
            "ts_utc": self.clock.utc_str(),
        }, retain=True)

    def publish_all_states(self):
        """
        Report every relay's state; called each time the MQTT link comes up.

        After a reboot all relays are off, which the server would otherwise
        not know about. The server logs only states that differ from its
        record, so a plain reconnect adds nothing. Reported as ``"auto"`` so
        the server's automation (not a manual override) decides what next.
        """
        for number in range(1, 9):
            self.publish_state(number, "auto")

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
        events = self.buttons.take_events()
        if events:
            self._last_activity = now
            if not self.display.backlight:
                # The first press only wakes the screen; it is not a command.
                self.display.set_backlight(True)
                self.pending = {}
                return
        for index, at in events:
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
            str: ``"OK"``, ``"NoMQTT"`` or ``"NoWiFi"``, followed by
            ``" LOCAL"`` while local mode is running; just ``"LOCAL"`` for
            a standalone controller whose Wi-Fi is fine (or not used).
        """
        if self.standalone:
            return "LOCAL" if self.net.wifi_ok or not self.config["wifi_ssid"] else "NoWiFi LOCAL"
        if self.net.mqtt_ok:
            return "OK"
        status = "NoMQTT" if self.net.wifi_ok else "NoWiFi"
        return status + " LOCAL" if self.local_mode else status

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
