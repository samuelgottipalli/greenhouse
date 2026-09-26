"""
Smoke test for picoside/device/main.py: import it (which boots the device)
with fake hardware and stop the endless loop after a few passes.
"""
import importlib
import json
import sys

import pytest

from pico_fakes import FakeWDT


class StopLoop(BaseException):
    """Not an Exception, so main.py's crash handler does not catch it."""


@pytest.fixture
def boot(fake_env, monkeypatch, tmp_path, ticks):
    config = {"wifi_ssid": "net", "wifi_password": "pw", "mqtt_broker": "broker.local"}
    (tmp_path / "config.json").write_text(json.dumps(config))
    monkeypatch.chdir(tmp_path)
    fake_env.network.WLAN = lambda mode: _connected_wlan()
    fake_env.ntptime.settime = lambda: None

    def _boot(max_ticks=3):
        controller = importlib.import_module("controller")
        passes = []
        real_tick = controller.Controller.tick

        def counted_tick(self):
            passes.append(self)
            if len(passes) > max_ticks:
                raise StopLoop
            real_tick(self)

        monkeypatch.setattr(controller.Controller, "tick", counted_tick)
        with pytest.raises(StopLoop):
            importlib.import_module("main")
        return passes

    return _boot


def _connected_wlan():
    from pico_fakes import FakeWLAN

    wlan = FakeWLAN()
    wlan.connected = True
    return wlan


def test_boot_runs_loop_with_watchdog(boot, monkeypatch):
    import types

    usocket = types.ModuleType("usocket")

    def unreachable(host, port):
        raise OSError(-2)

    usocket.getaddrinfo = unreachable
    usocket.socket = lambda: types.SimpleNamespace(settimeout=lambda t: None, close=lambda: None)
    import binascii
    import struct

    monkeypatch.setitem(sys.modules, "usocket", usocket)
    monkeypatch.setitem(sys.modules, "ustruct", struct)
    monkeypatch.setitem(sys.modules, "ubinascii", binascii)

    passes = boot()
    controller = passes[0]
    assert len(passes) == 4
    (watchdog,) = FakeWDT.instances
    # One feed per loop pass, plus one before the MQTT retry inside net.poll().
    assert watchdog.timeout == 8000 and watchdog.feeds >= 3
    assert controller.net.feed == watchdog.feed
    assert controller.sensors.read_dht() == (21.5, 45.0)
    assert controller.net.outbox  # broker unreachable: telemetry queued
