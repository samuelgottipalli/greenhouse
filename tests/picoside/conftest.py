"""
Fake MicroPython environment so the firmware in picoside/device/ runs on CPython.

Installs stand-ins for ``machine``, ``dht``, ``network``, ``ntptime`` and the
``i2c_lcd`` driver, and adds MicroPython's ``ticks_*``/``sleep_ms`` functions to
``time``. ``FakeTicks`` wraps at 2**30 exactly like the RP2040 port, so wrap-around
bugs show up in tests. The real vendored ``umqtt.simple`` is used where a test
needs MQTT bytes (``test_net.py``).
"""
import importlib
import sys
import time
import types

import pytest

from pico_fakes import FakeADC, FakeDHT22, FakeLcd, FakePin, FakeTicks, FakeWDT, FakeWLAN
from support import PICO_DIR

DEVICE_MODULES = ("config", "clock", "display", "relays", "sensors", "buttons", "net", "controller", "main")


@pytest.fixture
def ticks():
    return FakeTicks()


@pytest.fixture
def fake_env(monkeypatch, ticks):
    """Install the fake MicroPython modules and put the device code on sys.path."""
    machine = types.ModuleType("machine")
    machine.Pin = FakePin
    machine.ADC = FakeADC
    machine.I2C = lambda *a, **k: object()
    machine.WDT = FakeWDT
    machine.reset = lambda: None
    FakeWDT.instances = []

    dht = types.ModuleType("dht")
    dht.DHT22 = FakeDHT22
    network = types.ModuleType("network")
    network.STA_IF = 0
    network.WLAN = FakeWLAN
    ntptime = types.ModuleType("ntptime")
    ntptime.host = None
    ntptime.settime = lambda: None
    i2c_lcd = types.ModuleType("i2c_lcd")
    i2c_lcd.I2cLcd = FakeLcd

    for name, module in {"machine": machine, "dht": dht, "network": network,
                         "ntptime": ntptime, "i2c_lcd": i2c_lcd}.items():
        monkeypatch.setitem(sys.modules, name, module)
    for name in ("ticks_ms", "ticks_diff", "ticks_add", "sleep_ms"):
        monkeypatch.setattr(time, name, getattr(ticks, name), raising=False)
    monkeypatch.syspath_prepend(str(PICO_DIR / "lib"))
    monkeypatch.syspath_prepend(str(PICO_DIR))
    for name in DEVICE_MODULES + ("umqtt", "umqtt.simple"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    yield types.SimpleNamespace(machine=machine, network=network, ntptime=ntptime)
    for name in DEVICE_MODULES + ("umqtt", "umqtt.simple"):
        sys.modules.pop(name, None)


@pytest.fixture
def pico(fake_env):
    """Freshly imported device modules (everything except ``main``)."""
    return types.SimpleNamespace(
        **{name: importlib.import_module(name) for name in DEVICE_MODULES if name != "main"}
    )


@pytest.fixture
def config(pico):
    """Defaults plus a Wi-Fi network and broker, as a configured device has."""
    cfg = pico.config.load_config("no_such_file.json")
    cfg.update({"wifi_ssid": "greenhouse-net", "wifi_password": "pw", "mqtt_broker": "broker.local"})
    return cfg
