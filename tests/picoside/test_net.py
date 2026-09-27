"""
Tests for picoside/device/net.py.

Most tests use a scripted fake MQTT client. The last group runs the real
vendored ``umqtt.simple`` over a fake broker socket, so the actual MQTT bytes
(CONNECT with last will, SUBSCRIBE, PUBLISH) are exercised.
"""
import binascii
import json
import struct
import sys
import types

import pytest

from pico_fakes import FakeWLAN


class FakeClient:
    """Stands in for umqtt.simple.MQTTClient and records calls."""

    instances = []
    fail_connect = False

    def __init__(self, client_id, server, port=0, user=None, password=None, keepalive=0):
        self.args = dict(client_id=client_id, server=server, port=port, user=user,
                         password=password, keepalive=keepalive)
        self.calls = []
        self.published = []
        self.cb = None
        self.incoming = []
        self.fail_next = None
        self.sock = types.SimpleNamespace(close=lambda: self.calls.append("close"))
        FakeClient.instances.append(self)

    def set_callback(self, cb):
        self.calls.append("set_callback")
        self.cb = cb

    def set_last_will(self, topic, msg, retain=False, qos=0):
        self.calls.append(("will", topic, msg, retain))

    def connect(self, clean_session=True):
        self.calls.append("connect")
        if FakeClient.fail_connect:
            raise OSError(113)

    def subscribe(self, topic, qos=0):
        assert self.cb is not None, "Subscribe callback is not set"
        self.calls.append(("subscribe", topic))

    def publish(self, topic, msg, retain=False, qos=0):
        if self.fail_next:
            err, self.fail_next = self.fail_next, None
            raise err
        self.published.append((topic, msg, retain))

    def check_msg(self):
        if self.fail_next:
            err, self.fail_next = self.fail_next, None
            raise err
        while self.incoming:
            item = self.incoming.pop(0)
            topic, payload = item if isinstance(item, tuple) else (b"greenhouse/1/relay/set", item)
            self.cb(topic, payload)

    def ping(self):
        self.calls.append("ping")


@pytest.fixture
def make_net(pico, config):
    FakeClient.instances = []
    FakeClient.fail_connect = False

    def _make(connected=True, **overrides):
        config.update(overrides)
        wlan = FakeWLAN()
        wlan.connected = connected
        net = pico.net.Network(config, wlan=wlan, client_factory=FakeClient)
        commands = []
        net.on_command = commands.append
        net.commands = commands
        return net

    return _make


def test_topics(make_net):
    net = make_net(device_id=3, mqtt_topic_prefix="gh")
    assert net.topic("telemetry") == "gh/3/telemetry"


def test_connect_wifi_waits_until_connected(make_net, ticks):
    net = make_net(connected=False)
    assert net.connect_wifi() is True
    assert net.wlan.connect_calls == ["greenhouse-net"] and net.wlan.is_active


def test_connect_wifi_times_out_and_feeds_watchdog(make_net, ticks):
    net = make_net(connected=False)
    net.wlan.connect_succeeds = False
    feeds = []
    net.feed = lambda: feeds.append(1)
    start = ticks.now
    assert net.connect_wifi(timeout_ms=2000) is False
    assert ticks.ticks_diff(ticks.now, start) >= 2000
    assert len(feeds) >= 7


def test_connect_wifi_without_ssid(make_net):
    assert make_net(connected=False, wifi_ssid="").connect_wifi() is False


def test_connect_mqtt_sequence(make_net):
    net = make_net(mqtt_user="u", mqtt_password="p")
    assert net.connect_mqtt() is True and net.mqtt_ok
    client = FakeClient.instances[-1]
    assert client.args == dict(client_id="greenhouse_pico", server="broker.local", port=1883,
                               user="u", password="p", keepalive=300)
    assert client.calls[:4] == [
        "set_callback",
        ("will", "greenhouse/1/status", "offline", True),
        "connect",
        ("subscribe", "greenhouse/1/relay/set"),
    ]
    assert client.published == [("greenhouse/1/status", "online", True)]


def test_connect_mqtt_failure_is_not_raised(make_net):
    FakeClient.fail_connect = True
    net = make_net()
    assert net.connect_mqtt() is False and not net.mqtt_ok


def test_commands_are_decoded_and_forwarded(make_net, ticks):
    net = make_net()
    net.connect_mqtt()
    client = FakeClient.instances[-1]
    client.incoming = [b'{"relay": 2, "state": 1}', b"not json", b"[1, 2]"]
    net.poll(ticks.now)
    assert net.commands == [{"relay": 2, "state": 1}]


def test_publish_when_online(make_net):
    net = make_net()
    net.connect_mqtt()
    net.publish("telemetry", {"t": 1})
    assert FakeClient.instances[-1].published[-1] == ("greenhouse/1/telemetry", '{"t": 1}', False)
    assert net.outbox == []


def test_offline_messages_are_queued_then_flushed(make_net, ticks):
    net = make_net()
    net.publish("telemetry", {"n": 1})
    net.publish("relay/2/state", {"n": 2}, retain=True)
    assert len(net.outbox) == 2
    net.poll(ticks.now)  # connects, then flushes in order
    sent = FakeClient.instances[-1].published
    assert sent[1:] == [("greenhouse/1/telemetry", '{"n": 1}', False),
                        ("greenhouse/1/relay/2/state", '{"n": 2}', True)]
    assert net.outbox == []


def test_outbox_keeps_newest(make_net, pico):
    net = make_net()
    for n in range(pico.net.OUTBOX_MAX + 10):
        net.publish("telemetry", {"n": n})
    assert len(net.outbox) == pico.net.OUTBOX_MAX
    assert json.loads(net.outbox[0][1]) == {"n": 10}


def test_failed_publish_keeps_message_and_drops_session(make_net):
    net = make_net()
    net.connect_mqtt()
    FakeClient.instances[-1].fail_next = OSError(104)
    net.publish("telemetry", {"n": 1})
    assert not net.mqtt_ok
    assert len(net.outbox) == 1


def test_wifi_reconnect_backoff(make_net, ticks, pico):
    net = make_net(connected=False)
    net.wlan.connect_succeeds = False
    net.poll(ticks.now)
    assert len(net.wlan.connect_calls) == 1
    ticks.advance(1000)
    net.poll(ticks.now)
    assert len(net.wlan.connect_calls) == 1  # still backing off
    ticks.advance(pico.net.BACKOFF_START_MS * 2)
    net.poll(ticks.now)
    assert len(net.wlan.connect_calls) == 2


def test_mqtt_reconnect_backoff_grows_and_resets(make_net, ticks):
    FakeClient.fail_connect = True
    net = make_net()
    net.poll(ticks.now)
    net.poll(ticks.now)
    assert len(FakeClient.instances) == 1
    ticks.advance(4000)
    net.poll(ticks.now)
    assert len(FakeClient.instances) == 2
    ticks.advance(4000)
    net.poll(ticks.now)
    assert len(FakeClient.instances) == 2  # backoff now 8 s
    FakeClient.fail_connect = False
    ticks.advance(4000)
    net.poll(ticks.now)
    assert net.mqtt_ok


def test_lost_link_is_detected(make_net, ticks):
    net = make_net()
    net.connect_mqtt()
    FakeClient.instances[-1].fail_next = OSError(-1)
    net.poll(ticks.now)
    assert not net.mqtt_ok


def test_wifi_drop_ends_mqtt_session(make_net, ticks):
    net = make_net()
    net.connect_mqtt()
    net.wlan.connected = False
    net.wlan.connect_succeeds = False
    net.poll(ticks.now)
    assert not net.mqtt_ok and "close" in FakeClient.instances[-1].calls


def test_keepalive_ping_every_two_minutes(make_net, ticks):
    net = make_net()
    net.connect_mqtt()
    ticks.advance(119_000)
    net.poll(ticks.now)
    assert "ping" not in FakeClient.instances[-1].calls
    ticks.advance(2_000)
    net.poll(ticks.now)
    assert FakeClient.instances[-1].calls.count("ping") == 1


def test_silent_broker_is_treated_as_dead(make_net, ticks):
    net = make_net()
    net.connect_mqtt()
    client = FakeClient.instances[-1]
    client.last_rx = ticks.now
    ticks.advance(299_000)
    net.poll(ticks.now)
    assert net.mqtt_ok  # silent for less than the 5-minute keep-alive
    ticks.advance(2_000)
    net.poll(ticks.now)
    assert not net.mqtt_ok  # a whole keep-alive without a reply: reconnect


def test_ping_replies_keep_link_alive(make_net, ticks):
    net = make_net()
    net.connect_mqtt()
    client = FakeClient.instances[-1]
    for _ in range(10):  # 10 ping cycles; the broker answers each one
        ticks.advance(120_000)
        client.last_rx = ticks.now
        net.poll(ticks.now)
    assert net.mqtt_ok and client.calls.count("ping") == 10


def test_wifi_power_save_requested(make_net):
    net = make_net(connected=False)
    net.connect_wifi()
    assert net.wlan.pm == net.wlan.PM_POWERSAVE


def test_wifi_power_save_can_be_disabled(make_net):
    net = make_net(connected=False, wifi_power_save=False)
    net.connect_wifi()
    assert net.wlan.pm is None


def test_ip_address(make_net):
    net = make_net()
    assert net.ip_address() == "192.168.1.50"
    net.wlan.connected = False
    assert net.ip_address() is None


# --- real umqtt.simple over a fake broker socket ----------------------------

CONNACK_OK = b"\x20\x02\x00\x00"
SUBACK_OK = b"\x90\x03\x00\x01\x00"  # packet id 1: relay/set
SUBACK_2_OK = b"\x90\x03\x00\x02\x00"  # packet id 2: settings


def publish_packet(topic: bytes, payload: bytes) -> bytes:
    body = struct.pack("!H", len(topic)) + topic + payload
    return bytes([0x30, len(body)]) + body


class FakeBrokerSocket:
    """Replays scripted broker bytes; returns None when idle, like a non-blocking MicroPython socket."""

    def __init__(self, replies: bytes):
        self.replies = bytearray(replies)
        self.sent = bytearray()
        self.timeouts = []

    def connect(self, addr):
        pass

    def settimeout(self, value):
        self.timeouts.append(value)

    def setblocking(self, flag):
        pass

    def write(self, data, length=None):
        if isinstance(data, str):  # MicroPython sockets accept str as UTF-8
            data = data.encode()
        self.sent += bytes(data[:length] if length is not None else data)

    def read(self, n):
        if not self.replies:
            return None
        chunk, self.replies = bytes(self.replies[:n]), self.replies[n:]
        return chunk

    def close(self):
        pass


@pytest.fixture
def broker(monkeypatch, fake_env):
    sock = FakeBrokerSocket(CONNACK_OK + SUBACK_OK + SUBACK_2_OK)
    usocket = types.ModuleType("usocket")
    usocket.socket = lambda: sock
    usocket.getaddrinfo = lambda host, port: [(None, None, None, None, ("127.0.0.1", port))]
    monkeypatch.setitem(sys.modules, "usocket", usocket)
    monkeypatch.setitem(sys.modules, "ustruct", struct)
    monkeypatch.setitem(sys.modules, "ubinascii", binascii)
    return sock


def test_real_client_connects_subscribes_and_receives(pico, config, broker, ticks):
    # Formerly known bug P-01: subscribe() without set_callback() crashed boot.
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan)
    received = []
    net.on_command = received.append
    assert net.connect_mqtt() is True
    sent = bytes(broker.sent)
    assert sent[0] == 0x10 and b"greenhouse/1/status" in sent and b"offline" in sent  # CONNECT + will
    assert b"greenhouse/1/relay/set" in sent  # SUBSCRIBE
    assert sent.endswith(b"online")
    assert broker.timeouts[0] == 5

    assert net.client.last_rx == ticks.now  # CONNACK counts as hearing from the broker
    ticks.advance(1000)
    broker.replies += publish_packet(b"greenhouse/1/relay/set", b'{"relay": 4, "state": 0}')
    net.poll(ticks.now)
    assert net.client.last_rx == ticks.now
    net.poll(ticks.now)  # idle socket: read() returns None, nothing happens
    assert received == [{"relay": 4, "state": 0}]
    assert net.mqtt_ok


def test_real_client_unreachable_broker(pico, config, broker):
    def unreachable(host, port):
        raise OSError(-2)

    sys.modules["usocket"].getaddrinfo = unreachable
    wlan = FakeWLAN()
    wlan.connected = True
    assert pico.net.Network(config, wlan=wlan).connect_mqtt() is False
