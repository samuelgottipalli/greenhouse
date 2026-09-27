"""
Tests for the controller's own safety rules and local mode (P-15):
picoside/device/local_rules.py and its use in controller.py.
"""
import json
from datetime import datetime

import pytest

from pico_fakes import FakeLcd
from test_controller import FakeButtons, FakeClock, FakeNet, FakeSensors

SETTINGS = {
    "fan_on_temp_c": [30.0, 2.0],
    "fan_on_humidity_pct": [70.0, 5.0],
    "heater_on_temp_c": [10.0, 2.0],
    "watering": [["06:00", 30], ["23:50", 20], ["00:00", 0], ["00:00", 0]],
}


# --- pure rules -----------------------------------------------------------------

@pytest.fixture
def rules(pico):
    return pico.local_rules


@pytest.mark.parametrize(
    "payload, ok",
    [
        (SETTINGS, True),
        ({**SETTINGS, "fan_on_temp_c": [30]}, False),
        ({**SETTINGS, "heater_on_temp_c": [True, 2]}, False),
        ({**SETTINGS, "watering": [["6:00", 30]]}, False),
        ({**SETTINGS, "watering": [["06:00", "30"]]}, False),
        ({k: v for k, v in SETTINGS.items() if k != "watering"}, False),
        ([1, 2], False),
    ],
)
def test_valid_settings(rules, payload, ok):
    assert rules.valid_settings(payload) is ok


@pytest.mark.parametrize(
    "minutes, expected",
    [(360, True), (389, True), (390, False), (1435, True), (5, True), (10, False), (None, False)],
)
def test_watering_now(rules, minutes, expected):
    assert rules.watering_now(SETTINGS["watering"], minutes) is expected


def test_no_settings_means_safety_only(rules):
    assert rules.decide(None, 5.0, 90.0, {"fan": 1, "heater": 1, "water": 1}, 400) == {"heater": 0, "water": 0}


def test_no_temperature_turns_heater_off(rules):
    targets = rules.decide(SETTINGS, None, None, {"fan": 1, "heater": 1, "water": 0}, 400)
    assert targets == {"heater": 0, "water": 0}  # fan left as it is


def test_settings_file_round_trip(rules, tmp_path):
    path = str(tmp_path / "settings.json")
    assert rules.load_settings(path) is None
    assert rules.save_settings(SETTINGS, path)
    assert rules.load_settings(path) == SETTINGS
    (tmp_path / "settings.json").write_text("{broken")
    assert rules.load_settings(path) is None


def test_device_and_server_rules_agree(rules):
    """The device's local rules must match the server's for fan and heater."""
    from core import automation as server

    limits = {k: tuple(v) for k, v in SETTINGS.items() if k != "watering"}
    temps = [None, 5, 9.9, 10, 11, 11.9, 12, 20, 28, 29, 30, 31]
    hums = [None, 50, 64, 65, 66, 70, 71, 90]
    for temp in temps:
        for hum in hums:
            for on in (False, True):
                assert rules.fan_target(SETTINGS, temp, hum, on) == server.fan_target(limits, temp, hum, on)[0], (temp, hum, on)
                assert rules.heater_target(SETTINGS, temp, on) == server.heater_target(limits, temp, on)[0], (temp, on)


def test_watering_agrees_with_server(rules):
    from core import automation as server

    schedule = [tuple(slot) for slot in SETTINGS["watering"]]
    for minute in range(0, 1440, 7):
        local = datetime(2026, 9, 26, minute // 60, minute % 60)
        assert rules.watering_now(SETTINGS["watering"], minute) == server.watering_now(schedule, local), minute


# --- controller -----------------------------------------------------------------

class LocalClock(FakeClock):
    def __init__(self, minutes=12 * 60):
        super().__init__()
        self.minutes = minutes

    def local_minutes(self):
        return self.minutes if self.set else None


@pytest.fixture
def ctl(pico, config, ticks):
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), FakeNet(), LocalClock(),
    )
    controller.start()
    controller.tick()
    return controller


def run_for(ctl, ticks, ms, step=1000):
    for _ in range(ms // step):
        ticks.advance(step)
        ctl.tick()


def go_offline(ctl, ticks, ms=2 * 60 * 1000 + 30_000):
    ctl.net.mqtt_ok = False
    ctl.net.wifi_ok = False
    run_for(ctl, ticks, ms)


def test_settings_are_kept_and_saved(ctl, tmp_path):
    assert ctl.handle_settings(SETTINGS) is True
    assert ctl.settings == SETTINGS
    assert json.loads((tmp_path / "settings.json").read_text()) == SETTINGS
    assert ctl.handle_settings(SETTINGS) is False  # unchanged: no flash write
    assert ctl.handle_settings({"bad": 1}) is False
    assert ctl.settings == SETTINGS


def test_saved_settings_survive_reboot(pico, config, tmp_path):
    pico.local_rules.save_settings(SETTINGS)
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), FakeNet(), LocalClock(),
    )
    assert controller.settings == SETTINGS


def test_settings_message_reaches_controller(pico, config):
    from pico_fakes import FakeWLAN
    from test_net import FakeClient

    FakeClient.instances = []
    FakeClient.fail_connect = False
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan, client_factory=FakeClient)
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), net, LocalClock(),
    )
    net.connect_mqtt()
    assert ("subscribe", "greenhouse/1/settings") in FakeClient.instances[-1].calls
    FakeClient.instances[-1].cb(b"greenhouse/1/settings", json.dumps(SETTINGS).encode())
    assert controller.settings == SETTINGS


def test_local_mode_starts_after_two_minutes(ctl, ticks):
    ctl.net.mqtt_ok = False
    ctl.net.wifi_ok = False
    run_for(ctl, ticks, 110_000)
    assert not ctl.local_mode
    run_for(ctl, ticks, 20_000)
    assert ctl.local_mode
    assert ctl.display.lcd.screen[3].rstrip().endswith("NoWiFi LOCAL")


def test_local_mode_runs_heater_rule(ctl, ticks):
    ctl.handle_settings(SETTINGS)
    ctl.sensors.dht = (5.0, 50.0)
    go_offline(ctl, ticks)
    assert ctl.relays.state(3) == 1  # heater on locally
    ctl.sensors.dht = (11.0, 50.0)
    run_for(ctl, ticks, 65_000)  # one sensor interval
    assert ctl.relays.state(3) == 1  # within buffer
    ctl.sensors.dht = (12.5, 50.0)
    run_for(ctl, ticks, 65_000)  # one sensor interval
    assert ctl.relays.state(3) == 0
    sources = {p["source"] for s, p, _ in ctl.net.published if s == "relay/3/state"}
    assert sources == {"auto"}  # queued as automatic changes


def test_local_mode_waters_on_schedule(ctl, ticks):
    ctl.handle_settings(SETTINGS)
    ctl.clock.minutes = 6 * 60 + 5
    go_offline(ctl, ticks)
    assert ctl.relays.state(1) == 1
    ctl.clock.minutes = 7 * 60
    run_for(ctl, ticks, 35_000)
    assert ctl.relays.state(1) == 0


def test_local_mode_without_settings_is_safety_only(ctl, ticks):
    for relay in (1, 2, 3):
        ctl.relays.set(relay, 1)
    go_offline(ctl, ticks)
    assert (ctl.relays.state(1), ctl.relays.state(2), ctl.relays.state(3)) == (0, 1, 0)


def test_local_mode_ends_when_link_returns(ctl, ticks):
    ctl.handle_settings(SETTINGS)
    go_offline(ctl, ticks)
    assert ctl.local_mode
    ctl.net.mqtt_ok = ctl.net.wifi_ok = True
    ctl.relays.set(3, 1)  # e.g. server command
    ctl.sensors.dht = (25.0, 50.0)
    run_for(ctl, ticks, 60_000)
    assert not ctl.local_mode
    assert ctl.relays.state(3) == 1  # server is in charge again


def test_sensor_fault_turns_heater_off_even_online(ctl, ticks):
    ctl.handle_command({"relay": 3, "state": 1})
    ctl.sensors.dht = (None, None)
    run_for(ctl, ticks, 4 * 60 * 1000)
    assert ctl.relays.state(3) == 1  # 4 min: still trusted
    run_for(ctl, ticks, 90_000)
    assert ctl.relays.state(3) == 0
    assert ctl.net.published[-1][1]["source"] == "auto"


def test_healthy_sensor_never_trips_safety(ctl, ticks):
    ctl.handle_command({"relay": 3, "state": 1})
    run_for(ctl, ticks, 20 * 60 * 1000, step=5000)
    assert ctl.relays.state(3) == 1


# --- timing with the low-power defaults ----------------------------------------------

def test_heater_cutoff_is_at_five_minutes_not_next_read(ctl, ticks):
    ctl.handle_command({"relay": 3, "state": 1})
    ctl.sensors.dht = (None, None)
    run_for(ctl, ticks, 5 * 60 * 1000 - 5_000, step=1000)
    assert ctl.relays.state(3) == 1
    run_for(ctl, ticks, 10_000, step=1000)  # checked every pass, not only on the 60 s reads
    assert ctl.relays.state(3) == 0


def test_local_mode_acts_as_soon_as_it_starts(ctl, ticks):
    ctl.handle_settings(SETTINGS)
    ctl.sensors.dht = (5.0, 50.0)
    ctl.net.mqtt_ok = ctl.net.wifi_ok = False
    run_for(ctl, ticks, 119_000, step=1000)
    assert ctl.relays.state(3) == 0 and not ctl.local_mode
    run_for(ctl, ticks, 2_000, step=1000)
    assert ctl.local_mode and ctl.relays.state(3) == 1
