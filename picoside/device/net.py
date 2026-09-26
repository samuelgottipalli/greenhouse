"""
Wi-Fi and MQTT connectivity for the greenhouse controller.

``Network`` owns the Wi-Fi interface and the MQTT client. The main loop calls
:meth:`Network.poll` every pass; it reconnects with backoff when either link
is down, delivers incoming commands, sends keep-alive pings and flushes queued
messages. Messages published while offline are queued (the newest
``OUTBOX_MAX`` are kept) and sent after reconnecting.

Topics (``<prefix>/<device_id>/...``, see docs/MQTT.md):

* ``telemetry``: sensor snapshot (published by the controller).
* ``relay/<n>/state``: relay state after every change (retained).
* ``status``: ``"online"``, or ``"offline"`` via the last will (retained).
* ``relay/set``: commands ``{"relay": n, "state": 0|1}`` (subscribed).
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
        self.feed = None
        self._base = "{}/{}".format(config["mqtt_topic_prefix"], config["device_id"])
        self._keepalive_ms = config["mqtt_keepalive_s"] * 1000
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

    @property
    def wifi_ok(self):
        """bool: True while Wi-Fi is connected."""
        return self.wlan.isconnected()

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
        self.wlan.active(True)
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
        Decode an incoming command and pass it to ``on_command``.

        Args:
            topic (bytes): Topic the message arrived on.
            msg (bytes): JSON payload.
        """
        try:
            command = json.loads(msg)
        except ValueError:
            print("Ignoring non-JSON message on", topic)
            return
        if self.on_command and isinstance(command, dict):
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
                self.wlan.active(True)
                self.wlan.connect(self.config["wifi_ssid"], self.config["wifi_password"])
                self._schedule_retry(now, False)
            return
        if not self.mqtt_ok:
            if not self._attempt_due(now):
                return
            self._schedule_retry(now, self.connect_mqtt())
            if not self.mqtt_ok:
                return
        try:
            self.client.check_msg()
            if time.ticks_diff(now, self._last_ping) >= self._keepalive_ms // 2:
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
