"""
Tests for encrypted broker connections from the server (Phase 7.1): the TLS
settings, the shared connection helpers, finding which bundled root a broker
needs (core/broker_tls.py) and the bundled roots themselves.
"""
import socket

import pytest

from core import broker_tls, mqtt, settings, setup_code
from support import PICO_DIR

tls_support = pytest.importorskip("tls_support")


@pytest.mark.parametrize("value, port, expected", [
    ("auto", 8883, True), ("auto", 1883, False), ("true", 1883, True), ("off", 8883, False),
    ("", 8883, True), ("YES", 1884, True),
])
def test_tls_setting(value, port, expected):
    assert settings.tls_enabled(value, port) is expected


def test_connection_without_tls(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_HOST", "localhost")
    monkeypatch.setattr(settings, "MQTT_PORT", 1883)
    monkeypatch.setattr(settings, "MQTT_USERNAME", None)
    monkeypatch.setattr(settings, "MQTT_TLS", False)
    assert mqtt.connection() == {"hostname": "localhost", "port": 1883, "auth": None, "tls": None}


def test_connection_to_a_cloud_broker(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_HOST", "abc.s1.eu.hivemq.cloud")
    monkeypatch.setattr(settings, "MQTT_PORT", 8883)
    monkeypatch.setattr(settings, "MQTT_USERNAME", "server")
    monkeypatch.setattr(settings, "MQTT_PASSWORD", "pw")
    monkeypatch.setattr(settings, "MQTT_TLS", True)
    monkeypatch.setattr(settings, "MQTT_CA_FILE", None)
    assert mqtt.connection() == {"hostname": "abc.s1.eu.hivemq.cloud", "port": 8883,
                                 "auth": {"username": "server", "password": "pw"}, "tls": {"ca_certs": None}}


@pytest.mark.parametrize("publish", ["relay", "settings", "firmware"])
def test_every_publish_uses_the_shared_settings(monkeypatch, publish):
    from core import firmware

    monkeypatch.setattr(settings, "MQTT_TLS", True)
    monkeypatch.setattr(settings, "MQTT_CA_FILE", "/etc/my-ca.pem")
    sent = []
    fake = lambda **kw: sent.append(kw)  # noqa: E731
    monkeypatch.setattr(mqtt, "single", fake)
    monkeypatch.setattr(firmware, "single", fake)
    if publish == "relay":
        assert mqtt.publish_relay_command(1, 1, "web")
    elif publish == "settings":
        assert mqtt.publish_device_settings({"a": 1})
    else:
        assert firmware.publish_update(1, {"version": "x", "files": []})
    assert sent[0]["tls"] == {"ca_certs": "/etc/my-ca.pem"}
    assert sent[0]["hostname"] == settings.MQTT_HOST


class FakeClient:
    def __init__(self):
        self.calls = []

    def username_pw_set(self, user, password):
        self.calls.append(("login", user, password))

    def tls_set(self, ca_certs=None):
        self.calls.append(("tls", ca_certs))


def test_configure_client(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_USERNAME", "server")
    monkeypatch.setattr(settings, "MQTT_PASSWORD", "pw")
    monkeypatch.setattr(settings, "MQTT_TLS", True)
    monkeypatch.setattr(settings, "MQTT_CA_FILE", None)
    client = FakeClient()
    mqtt.configure_client(client)
    assert client.calls == [("login", "server", "pw"), ("tls", None)]
    monkeypatch.setattr(settings, "MQTT_USERNAME", None)
    monkeypatch.setattr(settings, "MQTT_TLS", False)
    client = FakeClient()
    mqtt.configure_client(client)
    assert client.calls == []


def test_ingest_client_is_configured(monkeypatch):
    """services/ingest.py sets its long-lived client up with the shared helper."""
    from services import ingest

    source = (settings.SERVER_DIR / "services" / "ingest.py").read_text(encoding="utf-8")
    assert "configure_client(client)" in source and "username_pw_set" not in source
    assert ingest.configure_client is mqtt.configure_client


# --- addresses -------------------------------------------------------------------


def test_broker_and_server_addresses(monkeypatch):
    monkeypatch.setattr(setup_code, "lan_address", lambda: "192.168.1.20")
    monkeypatch.setattr(settings, "PUBLIC_HOST", "")
    monkeypatch.setattr(settings, "MQTT_HOST", "localhost")
    assert setup_code.broker_address() == setup_code.server_address() == "192.168.1.20"
    monkeypatch.setattr(settings, "MQTT_HOST", "abc.s1.eu.hivemq.cloud")
    # Controllers log in to the cloud broker but still fetch updates from this server.
    assert setup_code.broker_address() == "abc.s1.eu.hivemq.cloud"
    assert setup_code.server_address() == "192.168.1.20"


# --- finding the root ------------------------------------------------------------------


@pytest.fixture
def two_roots(tmp_path):
    """A local TLS 'broker' signed by one throwaway root, and a certs folder with it and a stranger."""
    good = tls_support.make_ca(tmp_path / "good", "Good Root")
    other = tls_support.make_ca(tmp_path / "other", "Other Root")
    certs = tmp_path / "certs"
    certs.mkdir()
    (certs / "aaa_other.py").write_text(tls_support.cert_module(other["root_pem"]))
    (certs / "zzz_good.py").write_text(tls_support.cert_module(good["root_pem"]))
    return good, certs


def test_find_root(two_roots):
    good, certs = two_roots
    with tls_support.tls_server(good["cert_file"], good["key_file"]) as port:
        assert broker_tls.find_root("localhost", port, certs) == "zzz_good"


def test_find_root_when_none_fits(two_roots, tmp_path):
    good, certs = two_roots
    (certs / "zzz_good.py").unlink()
    with tls_support.tls_server(good["cert_file"], good["key_file"]) as port:
        assert broker_tls.find_root("localhost", port, certs) is None


def test_find_root_when_unreachable(two_roots):
    _good, certs = two_roots
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # nothing listens here once closed
    with pytest.raises(OSError):
        broker_tls.find_root("localhost", port, certs, timeout=2)


def test_bundled_roots_order_and_contents():
    roots = broker_tls.bundled_roots()
    assert list(roots)[:3] == list(broker_tls.PREFERRED)
    assert len(roots) >= 10
    for name, pem in roots.items():
        assert pem.startswith("-----BEGIN CERTIFICATE-----"), name
        assert (PICO_DIR / "certs" / f"{name}.py").exists()


def test_bundled_roots_match_certifi(tmp_path):
    """The committed files are exactly what the script writes (Mozilla's copies)."""
    pytest.importorskip("certifi")
    from scripts import update_controller_certs as script

    names = script.write_all(tmp_path)
    for name in names:
        committed = (PICO_DIR / "certs" / f"{name}.py").read_bytes().replace(b"\r\n", b"\n")
        assert committed == (tmp_path / f"{name}.py").read_bytes(), name
    assert sorted(p.stem for p in (PICO_DIR / "certs").glob("*.py")) == sorted(names)


def test_controller_tries_roots_in_the_same_order():
    source = (PICO_DIR / "net.py").read_text(encoding="utf-8")
    assert f"PREFERRED_ROOTS = {broker_tls.PREFERRED!r}" in source


def test_certificates_travel_with_updates():
    from core import firmware

    paths = [entry["path"] for entry in firmware.manifest(url="")["files"]]
    assert "certs/isrg_root_x1.py" in paths
    assert len(paths) <= 64  # ota.MAX_FILES



def test_controller_restart_uses_the_shared_settings(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_TLS", True)
    monkeypatch.setattr(settings, "MQTT_CA_FILE", None)
    sent = []
    monkeypatch.setattr(mqtt, "single", lambda **kw: sent.append(kw))
    assert mqtt.publish_controller_restart(1)
    assert sent[0]["tls"] == {"ca_certs": None}
