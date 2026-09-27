"""
Wi-Fi and MQTT connectivity for the greenhouse controller.

``Network`` owns the Wi-Fi interface and the MQTT client. The main loop calls
:meth:`Network.poll` every pass; it reconnects with backoff when either link
is down, delivers incoming commands, sends keep-alive pings (every
``mqtt_ping_s``) and treats the link as dead if the broker stays silent for a
whole ``mqtt_keepalive_s``, and flushes queued
messages. Messages published while offline are queued (the newest
``OUTBOX_MAX`` are kept) and sent after reconnecting.

Topics (``<prefix>/<device_id>/...``, see docs/MQTT.md):

* ``telemetry``: sensor snapshot (published by the controller).
* ``relay/<n>/state``: relay state after every change (retained).
* ``status``: ``"online"``, or ``"offline"`` via the last will (retained).
* ``relay/set``: commands ``{"relay": n, "state": 0|1}`` (subscribed).
* ``settings``: automation settings for local mode (subscribed, retained).
* ``firmware/update``: an over-the-air update manifest (subscribed).
* ``firmware``: installed version and update progress (published, retained).
"""
import json
import time

OUTBOX_MAX = 48
BACKOFF_START_MS = 2000
BACKOFF_MAX_MS = 300000
WIFI_POLL_MS = 250


class Network:
    """
    Keeps Wi-Fi and MQTT connected and moves messages.

    Attributes:
        mqtt_ok (bool): True while the MQTT session is believed healthy.
        outbox (list[tuple[str, str, bool]]): Unsent ``(topic, payload, retain)``.
        on_command (callable | None): Called with each decoded command dict.
        on_settings (callable | None): Called with each decoded settings dict.
        on_firmware (callable | None): Called with each decoded update manifest.
        feed (callable | None): Called before slow operations (watchdog feed).
    """

    def __init__(self, config, wlan=None, client_factory=None):
        """
        Args:
            config (dict): Uses the ``wifi_*`` and ``mqtt_*`` keys and
                ``device_id``.
            wlan (object | None): Wi-Fi interface (injected in tests).
            client_factory (callable | None): Builds an MQTT client with the
                ``umqtt.simple.MQTTClient`` signature (injected in tests).
        """
        if wlan is None:
            import network

            wlan = network.WLAN(network.STA_IF)
        if client_factory is None:
            from umqtt.simple import MQTTClient as client_factory
        self.config = config
        self.wlan = wlan
        self._client_factory = client_factory
        self.client = None
        self.mqtt_ok = False
        self.outbox = []
        self.on_command = None
        self.on_settings = None
        self.on_firmware = None
        self.feed = None
        # Without a server (standalone, or no broker set) MQTT is never tried.
        self.server = not config.get("standalone") and config["mqtt_broker"] not in ("", "YOUR_MQTT_BROKER")
        self._base = "{}/{}".format(config["mqtt_topic_prefix"], config["device_id"])
        self._keepalive_ms = config["mqtt_keepalive_s"] * 1000
        self._ping_ms = config["mqtt_ping_s"] * 1000
        self._backoff_ms = BACKOFF_START_MS
        self._next_attempt = None
        self._last_ping = None

    def topic(self, suffix):
        """
        Build a topic under this device.

        Args:
            suffix (str): e.g. ``"telemetry"``.

        Returns:
            str: e.g. ``"greenhouse/1/telemetry"``.
        """
        return "{}/{}".format(self._base, suffix)

    def _feed(self):
        """Feed the watchdog, if one is attached."""
        if self.feed:
            self.feed()

    def _activate_wifi(self):
        """Switch the radio on, in power-save mode if ``wifi_power_save`` is set."""
        self.wlan.active(True)
        if not self.config["wifi_power_save"]:
            return
        mode = getattr(self.wlan, "PM_POWERSAVE", None)
        if mode is None:
            return
        try:
            self.wlan.config(pm=mode)
        except Exception as err:  # not supported by this firmware
            print("Wi-Fi power save unavailable:", err)

    def link_silent(self, now):
        """
        Tell whether the broker has been silent for longer than the keep-alive.

        The client pings every ``mqtt_ping_s`` and the broker always answers,
        so silence for a whole keep-alive period means the link is dead even if
        the socket has not reported an error (e.g. a router dropped it).

        Args:
            now (int): ``ticks_ms`` now.

        Returns:
            bool: True if the link should be treated as dead.
        """
        last_rx = getattr(self.client, "last_rx", None)
        return last_rx is not None and time.ticks_diff(now, last_rx) > self._keepalive_ms

    @property
    def wifi_ok(self):
        """bool: True while Wi-Fi is connected."""
        return self.wlan.isconnected()

    def rssi(self):
        """
        Return the Wi-Fi signal strength.

        Returns:
            int | None: dBm (e.g. -60; closer to 0 is stronger), or None when
            Wi-Fi is down or the port cannot report it.
        """
        if not self.wifi_ok:
            return None
        try:
            return int(self.wlan.status("rssi"))
        except Exception:
            return None

    def ip_address(self):
        """
        Return the device's IP address.

        Returns:
            str | None: Address, or None when Wi-Fi is down.
        """
        return self.wlan.ifconfig()[0] if self.wifi_ok else None

    def connect_wifi(self, timeout_ms=None):
        """
        Connect to Wi-Fi, waiting up to a timeout (used at boot).

        Args:
            timeout_ms (int | None): Give up after this long; defaults to
                ``wifi_timeout_s`` from config.

        Returns:
            bool: True if connected.
        """
        if timeout_ms is None:
            timeout_ms = self.config["wifi_timeout_s"] * 1000
        self._activate_wifi()
        if self.wlan.isconnected():
            return True
        if not self.config["wifi_ssid"]:
            return False
        self.wlan.connect(self.config["wifi_ssid"], self.config["wifi_password"])
        start = time.ticks_ms()
        while not self.wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), start) >= timeout_ms:
                return False
            self._feed()
            time.sleep_ms(WIFI_POLL_MS)
        return True

    def connect_mqtt(self):
        """
        Open an MQTT session: last will, connect, subscribe, announce online.

        Returns:
            bool: True if connected. Errors are printed, not raised.
        """
        self._drop_client()
        if not self.server:
            return False
        self._feed()
        try:
            client = self._client_factory(
                self.config["mqtt_client_id"],
                self.config["mqtt_broker"],
                port=self.config["mqtt_port"],
                user=self.config["mqtt_user"],
                password=self.config["mqtt_password"],
                keepalive=self.config["mqtt_keepalive_s"],
            )
            client.set_callback(self._on_message)
            client.set_last_will(self.topic("status"), "offline", retain=True)
            client.connect()
            client.subscribe(self.topic("relay/set"))
            client.subscribe(self.topic("settings"))
            client.subscribe(self.topic("firmware/update"))
            client.publish(self.topic("status"), "online", retain=True)
        except Exception as err:  # OSError, MQTTException, bad broker name, ...
            print("MQTT connect failed:", err)
            return False
        self.client = client
        self.mqtt_ok = True
        self._last_ping = time.ticks_ms()
        return True

    def _drop_client(self):
        """Forget the current MQTT session, closing its socket if possible."""
        if self.client is not None:
            try:
                self.client.sock.close()
            except Exception:
                pass
        self.client = None
        self.mqtt_ok = False

    def _on_message(self, topic, msg):
        """
        Decode an incoming message and pass it to ``on_settings`` (settings
        topic), ``on_firmware`` (update topic) or ``on_command`` (everything
        else).

        Args:
            topic (bytes): Topic the message arrived on.
            msg (bytes): JSON payload.
        """
        try:
            command = json.loads(msg)
        except ValueError:
            print("Ignoring non-JSON message on", topic)
            return
        if not isinstance(command, dict):
            return
        name = topic.decode() if isinstance(topic, bytes) else topic
        if name.endswith("/settings"):
            if self.on_settings:
                self.on_settings(command)
        elif name.endswith("/firmware/update"):
            if self.on_firmware:
                self.on_firmware(command)
        elif self.on_command:
            self.on_command(command)

    def _schedule_retry(self, now, success):
        """
        Reset the backoff after a success or double it after a failure.

        Args:
            now (int): ``ticks_ms`` now.
            success (bool): Outcome of the attempt.
        """
        if success:
            self._backoff_ms = BACKOFF_START_MS
        else:
            self._backoff_ms = min(self._backoff_ms * 2, BACKOFF_MAX_MS)
        self._next_attempt = time.ticks_add(now, self._backoff_ms)

    def _attempt_due(self, now):
        """Tell whether the backoff delay has passed."""
        return self._next_attempt is None or time.ticks_diff(now, self._next_attempt) >= 0

    def poll(self, now):
        """
        Do one pass of connection upkeep and message handling. Never blocks
        for long and never raises for network errors.

        Args:
            now (int): ``ticks_ms`` now.
        """
        if not self.wifi_ok:
            if self.mqtt_ok:
                self._drop_client()
            if self._attempt_due(now) and self.config["wifi_ssid"]:
                self._activate_wifi()
                self.wlan.connect(self.config["wifi_ssid"], self.config["wifi_password"])
                self._schedule_retry(now, False)
            return
        if not self.server:
            return
        if not self.mqtt_ok:
            if not self._attempt_due(now):
                return
            self._schedule_retry(now, self.connect_mqtt())
            if not self.mqtt_ok:
                return
        try:
            self.client.check_msg()
            if self.link_silent(now):
                raise OSError("no reply from broker for a whole keep-alive")
            if time.ticks_diff(now, self._last_ping) >= self._ping_ms:
                self.client.ping()
                self._last_ping = now
        except Exception as err:
            print("MQTT link lost:", err)
            self._drop_client()
            self._schedule_retry(now, False)
            return
        self.flush()

    def publish(self, suffix, payload, retain=False):
        """
        Send a JSON message, or queue it if MQTT is down.

        Args:
            suffix (str): Topic under this device, e.g. ``"telemetry"``.
            payload (dict): JSON-serialisable body.
            retain (bool): Ask the broker to keep it for new subscribers.
        """
        if not self.server:
            return
        self.outbox.append((self.topic(suffix), json.dumps(payload), retain))
        if len(self.outbox) > OUTBOX_MAX:
            self.outbox.pop(0)
        self.flush()

    def flush(self):
        """
        Send queued messages, oldest first, while MQTT is up.

        Returns:
            int: Number of messages sent.
        """
        sent = 0
        while self.mqtt_ok and self.outbox:
            topic, body, retain = self.outbox[0]
            try:
                self.client.publish(topic, body, retain=retain)
            except Exception as err:
                print("MQTT publish failed:", err)
                self._drop_client()
                break
            self.outbox.pop(0)
            sent += 1
        return sent
