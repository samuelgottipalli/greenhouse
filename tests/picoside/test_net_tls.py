"""
Tests for encrypted broker connections on the controller (Phase 7.2):
reading the bundled root certificates, checking a broker's certificate with
them (real TLS against a local server), and how ``Network`` picks a root,
waits for the clock and remembers the root that works.
"""
import socket
import ssl
import sys
import types

import pytest

from pico_fakes import FakeWLAN
from support import PICO_DIR
from test_net import CONNACK_OK, SUBACK_2_OK, SUBACK_3_OK, SUBACK_OK, FakeBrokerSocket, FakeClient

tls_support = pytest.importorskip("tls_support")


# --- bundled roots -------------------------------------------------------------------


def test_read_root_gives_the_certificate(pico):
    from core import broker_tls

    pem = broker_tls.bundled_roots()["isrg_root_x1"]
    assert pico.net.read_root("isrg_root_x1", str(PICO_DIR / "certs")) == ssl.PEM_cert_to_DER_cert(pem)


def test_root_names_order(pico, tmp_path):
    for name in ("zeta", "digicert_global_root_g2", "alpha", "isrg_root_x1"):
        (tmp_path / f"{name}.py").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    assert pico.net.root_names(str(tmp_path)) == ["isrg_root_x1", "digicert_global_root_g2", "alpha", "zeta"]
    assert pico.net.root_names(str(tmp_path / "missing")) == []
    assert pico.net.root_names(str(PICO_DIR / "certs"))[0] == "isrg_root_x1"


def test_read_root_rejects_a_file_without_a_certificate(pico, tmp_path):
    (tmp_path / "empty.py").write_text('"""Nothing here."""\n')
    with pytest.raises(ValueError):
        pico.net.read_root("empty", str(tmp_path))
    with pytest.raises(OSError):
        pico.net.read_root("missing", str(tmp_path))


def test_clock_is_set(pico, monkeypatch):
    assert pico.net.clock_is_set()  # this computer's clock
    monkeypatch.setattr(pico.net.time, "gmtime", lambda *a: (2021, 1, 1, 0, 0, 0, 4, 1), raising=False)
    assert not pico.net.clock_is_set()  # a Pico that hasn't synced shows 2021


# --- real certificate checks -------------------------------------------------------


@pytest.fixture
def ca(tmp_path):
    """A local TLS server signed by a throwaway root, and a certs folder with that root and a stranger."""
    good = tls_support.make_ca(tmp_path / "good", "Good Root")
    other = tls_support.make_ca(tmp_path / "other", "Other Root")
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "good.py").write_text(tls_support.cert_module(good["root_pem"]))
    (certs / "other.py").write_text(tls_support.cert_module(other["root_pem"]))
    return good, certs


def handshake(context, port, host="localhost"):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname=host):
            pass


def test_tls_context_accepts_the_right_root(pico, ca):
    good, certs = ca
    with tls_support.tls_server(good["cert_file"], good["key_file"]) as port:
        handshake(pico.net.tls_context("good", str(certs)), port)


def test_tls_context_refuses_another_root_as_a_value_error(pico, ca):
    """net.py treats ValueError as "wrong root" (MicroPython raises exactly that)."""
    good, certs = ca
    with tls_support.tls_server(good["cert_file"], good["key_file"]) as port:
        with pytest.raises(ValueError):
            handshake(pico.net.tls_context("other", str(certs)), port)


def test_tls_context_checks_the_name(pico, ca):
    good, certs = ca
    with tls_support.tls_server(good["cert_file"], good["key_file"]) as port:
        with pytest.raises(ValueError):
            handshake(pico.net.tls_context("good", str(certs)), port, host="evil.example")


# --- the real umqtt client with a context ------------------------------------------


class PicoTLSSocket:
    """Like MicroPython's TLS socket: read/write/setblocking/close, but no settimeout()."""

    def __init__(self, raw):
        self.raw = raw

    def read(self, n):
        return self.raw.read(n)

    def write(self, data, length=None):
        return self.raw.write(data, length)

    def setblocking(self, flag):
        self.raw.setblocking(flag)

    def close(self):
        self.raw.close()


class RecordingContext:
    """An SSL context stand-in: records the broker name and wraps the (fake) socket."""

    def __init__(self):
        self.names = []

    def wrap_socket(self, sock, server_hostname=None):
        self.names.append(server_hostname)
        return PicoTLSSocket(sock)


def test_umqtt_wraps_the_socket_with_the_broker_name(pico, config, monkeypatch, fake_env):
    import binascii
    import struct

    broker = FakeBrokerSocket(CONNACK_OK + SUBACK_OK + SUBACK_2_OK + SUBACK_3_OK)
    usocket = types.ModuleType("usocket")
    usocket.socket = lambda: broker
    usocket.getaddrinfo = lambda host, port: [(None, None, None, None, ("127.0.0.1", port))]
    monkeypatch.setitem(sys.modules, "usocket", usocket)
    monkeypatch.setitem(sys.modules, "ustruct", struct)
    monkeypatch.setitem(sys.modules, "ubinascii", binascii)
    context = RecordingContext()
    config.update(mqtt_broker="abc.s1.eu.hivemq.cloud", mqtt_port=8883, mqtt_tls=True, mqtt_ca="isrg_root_x1")
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan)
    net._tls_context = lambda name: context
    assert net.connect_mqtt() is True
    assert context.names == ["abc.s1.eu.hivemq.cloud"]
    assert bytes(broker.sent).endswith(b"online")
    # Found on the Pico: the TLS socket has no settimeout(), so umqtt sets timeouts on the TCP socket.
    assert isinstance(net.client.sock, PicoTLSSocket) and net.client.raw_sock is broker
    assert broker.timeouts.count(5) >= 4  # connect, then after each SUBACK read
    net.poll(0)  # check_msg on an idle TLS socket
    assert net.mqtt_ok


# --- choosing a root -------------------------------------------------------------------


class TLSClient(FakeClient):
    """FakeClient that accepts the ssl argument and fails for the wrong root."""

    good_root = "good"

    def __init__(self, *args, ssl=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.ssl = ssl

    def connect(self, clean_session=True):
        self.calls.append("connect")
        if TLSClient.network_down:
            raise OSError(113)
        if self.ssl != TLSClient.good_root:
            raise ValueError("The certificate is not correctly signed by the trusted CA")


@pytest.fixture
def tls_net(pico, config):
    TLSClient.instances = []
    TLSClient.network_down = False
    FakeClient.instances = []

    def make(**overrides):
        config.update(mqtt_broker="broker.example", mqtt_port=8883, mqtt_tls=True, mqtt_ca="")
        config.update(overrides)
        wlan = FakeWLAN()
        wlan.connected = True
        net = pico.net.Network(config, wlan=wlan, client_factory=TLSClient)
        net._tls_context = lambda name: name  # the fake client compares names
        net._root_names = lambda: ["first", "good", "last"]
        net._clock_is_set = lambda: True
        net.saved = []
        net._save_config = lambda cfg: net.saved.append(dict(cfg))
        return net

    return make


def tried(net):
    return [client.ssl for client in FakeClient.instances]


def test_finds_and_remembers_the_root(tls_net):
    net = tls_net()
    assert net.connect_mqtt() is True
    assert tried(net) == ["first", "good"]
    assert net.config["mqtt_ca"] == "good" and net.saved[-1]["mqtt_ca"] == "good"
    assert net.tls_error is None
    assert net.connect_mqtt() is True
    assert tried(net)[-1] == "good" and len(tried(net)) == 3  # straight to the saved root


def test_no_root_fits(tls_net):
    net = tls_net()
    TLSClient.good_root = "nobody"
    try:
        assert net.connect_mqtt() is False
    finally:
        TLSClient.good_root = "good"
    assert tried(net) == ["first", "good", "last"]
    assert net.tls_error == "certificate not trusted" and net.saved == []


def test_network_error_does_not_try_every_root(tls_net):
    net = tls_net()
    TLSClient.network_down = True
    assert net.connect_mqtt() is False
    assert tried(net) == ["first"]


def test_saved_root_that_stops_fitting_is_forgotten(tls_net):
    net = tls_net(mqtt_ca="first")
    assert net.connect_mqtt() is False
    assert tried(net) == ["first"] and net.config["mqtt_ca"] == ""
    assert net.connect_mqtt() is True  # next attempt searches again
    assert net.config["mqtt_ca"] == "good"


def test_waits_for_the_clock(tls_net):
    net = tls_net()
    net._clock_is_set = lambda: False
    assert net.connect_mqtt() is False
    assert FakeClient.instances == [] and net.tls_error == "clock not set"


def test_unreadable_root_is_skipped(tls_net):
    net = tls_net()

    def context(name):
        if name == "first":
            raise ValueError("no certificate in first")
        return name

    net._tls_context = context
    assert net.connect_mqtt() is True
    assert tried(net) == ["good"]


def test_plain_connection_passes_no_ssl_argument(make_net_plain):
    net = make_net_plain()
    assert net.connect_mqtt() is True
    assert "ssl" not in FakeClient.instances[-1].args


@pytest.fixture
def make_net_plain(pico, config):
    FakeClient.instances = []
    FakeClient.fail_connect = False

    def make():
        wlan = FakeWLAN()
        wlan.connected = True
        return pico.net.Network(config, wlan=wlan, client_factory=FakeClient)

    return make
