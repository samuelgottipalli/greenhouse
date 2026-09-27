"""Tests for installer/broker.py: Mosquitto files, scripts and the login check."""
import os
import socket
import types

import pytest

from installer import broker
from support import REPO_ROOT
from test_broker_acl import matches, parse_acl


def allowed(rules, user, access, topic):
    return any(mode in (access, "readwrite") and matches(pattern, topic) for pattern, mode in rules[user])


def test_acl_matches_the_deploy_file_for_controller_1():
    ours = parse_acl(broker.acl_text([1]))
    deploy = parse_acl((REPO_ROOT / "deploy" / "mosquitto" / "greenhouse.acl").read_text(encoding="utf-8"))
    assert ours == deploy


def test_acl_keeps_controllers_apart():
    rules = parse_acl(broker.acl_text([1, 2]))
    assert allowed(rules, "greenhouse-device-2", "write", "greenhouse/2/firmware")
    assert allowed(rules, "greenhouse-device-2", "read", "greenhouse/2/firmware/update")
    assert not allowed(rules, "greenhouse-device-2", "read", "greenhouse/1/relay/set")
    assert not allowed(rules, "greenhouse-device-1", "write", "greenhouse/2/telemetry")
    assert allowed(rules, "greenhouse-server", "write", "greenhouse/2/relay/set")


def test_conf_text():
    text = broker.conf_text(1884, "/p/passwd", "/p/acl", "C:/data/mosquitto")
    lines = text.splitlines()
    assert "listener 1884" in lines and "allow_anonymous false" in lines
    assert "password_file /p/passwd" in lines and "acl_file /p/acl" in lines
    assert "persistence_location C:/data/mosquitto/" in lines
    assert "persistence_location" not in broker.conf_text(1883, "a", "b")


def test_passwd_text():
    assert broker.passwd_text({"a": "1", "b": "2"}) == "a:1\nb:2\n"


def test_choose_port():
    assert broker.choose_port(lambda port: True) == 1883
    assert broker.choose_port(lambda port: port != 1883) == 1884
    assert broker.choose_port(lambda port: False) == 1884


def test_port_free_sees_a_listener():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    try:
        assert broker.port_free(listener.getsockname()[1], "127.0.0.1") is False
    finally:
        listener.close()


def test_install_command():
    assert broker.install_command("windows")[:2] == ["winget", "install"]
    assert broker.install_command("macos") == ["brew", "install", "mosquitto"]
    assert broker.install_command("linux") is None


def test_linux_script(tmp_path):
    folder = tmp_path / "with space"
    script = broker.linux_script(folder)
    lines = script.splitlines()
    assert lines[:2] == ["#!/bin/sh", "set -e"]
    assert "apt-get install -y mosquitto mosquitto-clients" in lines
    hash_line = next(i for i, line in enumerate(lines) if line.startswith("mosquitto_passwd -U"))
    install_line = next(i for i, line in enumerate(lines) if broker.LINUX_PASSWD in line)
    assert hash_line < install_line < lines.index("systemctl restart mosquitto")
    assert "'" in lines[hash_line]  # the path with a space is quoted
    assert "apt-get" not in broker.linux_script(folder, install=False)


def test_stage_linux(tmp_path):
    script = broker.stage_linux({"greenhouse-server": "s", "greenhouse-device-1": "d"}, [1], folder=tmp_path)
    assert script.name == "setup-broker.sh"
    assert (tmp_path / "greenhouse.passwd").read_text() == "greenhouse-server:s\ngreenhouse-device-1:d\n"
    assert "listener 1883" in (tmp_path / "greenhouse.conf").read_text()
    assert "user greenhouse-device-1" in (tmp_path / "greenhouse.acl").read_text()
    if os.name == "posix":
        assert (tmp_path / "greenhouse.passwd").stat().st_mode & 0o777 == 0o600


def test_write_local(tmp_path):
    calls = []

    def run(command, **kw):
        calls.append(command)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    conf = broker.write_local({"greenhouse-server": "s"}, [1, 2], 1884, folder=tmp_path, run=run,
                              find=lambda name: "/usr/bin/" + name)
    assert calls == [["/usr/bin/mosquitto_passwd", "-U", str(tmp_path / "passwd")]]
    text = conf.read_text()
    assert "listener 1884" in text and f"password_file {(tmp_path / 'passwd').as_posix()}" in text
    assert "user greenhouse-device-2" in (tmp_path / "acl").read_text()


def test_write_local_needs_mosquitto(tmp_path):
    with pytest.raises(RuntimeError, match="not installed"):
        broker.write_local({}, [1], 1883, folder=tmp_path, find=lambda name: None)

    def fail(command, **kw):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="bad file")

    with pytest.raises(RuntimeError, match="bad file"):
        broker.write_local({}, [1], 1883, folder=tmp_path, run=fail, find=lambda name: name)


class FakeMqtt:
    """A paho-like client whose connection result the test chooses."""

    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.login = None
        self.on_connect = self.on_message = None
        self.subscribed = []
        self.messages = []

    def username_pw_set(self, user, password):
        self.login = (user, password)

    def connect(self, host, port, keepalive=60):
        if self.error:
            raise self.error

    def loop_start(self):
        if self.result is not None:
            self.on_connect(self, None, None, self.result, None)
            for payload in self.messages:
                self.on_message(self, None, types.SimpleNamespace(payload=payload))

    def subscribe(self, topic):
        self.subscribed.append(topic)

    def loop_stop(self):
        pass

    def disconnect(self):
        pass


class Code:
    def __init__(self, failure):
        self.is_failure = failure

    def __str__(self):
        return "Not authorized" if self.is_failure else "Success"


def test_check_login_success():
    client = FakeMqtt(result=Code(False))
    ok, message = broker.check_login("h", 1883, "u", "p", client_factory=lambda: client)
    assert ok and "Logged in" in message and client.login == ("u", "p")


def test_check_login_refused_unreachable_or_silent():
    ok, message = broker.check_login("h", 1883, "u", "bad", client_factory=lambda: FakeMqtt(result=Code(True)))
    assert not ok and "refused" in message
    ok, message = broker.check_login("h", 1883, None, None,
                                     client_factory=lambda: FakeMqtt(error=ConnectionRefusedError(111, "no")))
    assert not ok and "Can't reach" in message
    ok, message = broker.check_login("h", 1883, None, None, timeout=0.01, client_factory=lambda: FakeMqtt())
    assert not ok and "didn't answer" in message
