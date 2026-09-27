"""
A controller that runs on its own, without a server (``"standalone": true``):
chosen on the setup page, it needs no setup code, Wi-Fi is optional, and it
runs the fan, heater and watering rules by itself from the moment it starts.
"""
import importlib
import json

import pytest

from pico_fakes import FakeLcd, FakeWLAN
from test_controller import FakeButtons, FakeClock, FakeSensors
from test_net import FakeClient
from test_provision import RecordingDisplay, hardware, no_broker, post  # noqa: F401 (fixtures)


@pytest.fixture
def solo(pico):
    """A standalone config: no server, and no Wi-Fi."""
    config = pico.config.load_config("no_such_file.json")
    config["standalone"] = True
    return config


def test_default_rules_match_the_server(pico):
    """The controller's factory rules are the server's factory settings."""
    from core import migrations

    import local_rules

    rules = local_rules.default_settings()
    assert local_rules.valid_settings(rules)
    for name, _relay, value, buffer in migrations.DEFAULT_THRESHOLDS:
        if name in rules:
            assert rules[name] == [value, buffer], name
    assert rules["watering"] == [[start, minutes] for _slot, _relay, start, minutes in migrations.DEFAULT_SCHEDULE]
    rules["watering"][0][1] = 99
    assert local_rules.default_settings()["watering"][0][1] == 30  # a fresh copy each time


def test_standalone_starts_without_setup(pico, solo):
    p = pico.provision
    assert p.setup_reason(solo, False) is None
    assert p.setup_reason(solo, True) == p.REASON_BUTTON
    assert pico.config.config_problems(solo) == []


def test_form_standalone_without_wifi(pico, solo):
    blank = pico.config.load_config("no_such_file.json")
    changes, errors = pico.provision.form_to_settings({"mode": "standalone", "ssid": "", "tz": "UTC"}, blank)
    assert errors == []
    assert changes["standalone"] is True and changes["wifi_ssid"] == "" and changes["mqtt_broker"] == ""


def test_form_standalone_still_checks_a_wifi_password(pico, solo):
    _changes, errors = pico.provision.form_to_settings(
        {"mode": "standalone", "ssid": "home", "password": "short", "tz": "UTC"}, solo)
    assert any("8 to 63" in e for e in errors)


def test_form_server_mode_needs_wifi_and_server(pico, solo):
    changes, errors = pico.provision.form_to_settings({"mode": "server", "ssid": "", "code": "", "tz": "UTC"}, solo)
    assert changes["standalone"] is False
    assert any("Wi-Fi network" in e for e in errors) and any("server's address" in e for e in errors)


def test_form_to_rules(pico):
    import local_rules

    current = local_rules.default_settings()
    current["watering"][2] = ["18:00", 5]
    rules, errors = pico.provision.form_to_rules(
        {"fan_t": "30.5", "fan_h": "70", "heat_t": "10", "w1": "07:15", "w1m": "20", "w2": "19:00", "w2m": "0"},
        current)
    assert errors == []
    assert rules["fan_on_temp_c"] == [30.5, 2.0] and rules["fan_on_humidity_pct"] == [70.0, 2.0]
    assert rules["heater_on_temp_c"] == [10.0, 2.0]
    assert rules["watering"] == [["07:15", 20], ["19:00", 0], ["18:00", 5], ["00:00", 0]]
    assert local_rules.valid_settings(rules)


@pytest.mark.parametrize("fields, message", [
    ({"fan_t": "hot"}, "numbers"),
    ({"fan_h": "150"}, "0 to 100"),
    ({"heat_t": "-40"}, "-20 to 60"),
    ({"w1": "25:00"}, "06:30"),
    ({"w2": "7:30"}, "06:30"),
    ({"w1m": "500"}, "0 to 240"),
    ({"w2m": "x"}, "0 to 240"),
])
def test_form_to_rules_errors(pico, fields, message):
    import local_rules

    _rules, errors = pico.provision.form_to_rules(fields, local_rules.default_settings())
    assert any(message in e for e in errors), errors


def test_setup_page_offers_both_ways(pico, solo):
    server = pico.config.load_config("no_such_file.json")
    html = pico.provision.render_setup_page(server, [], "new")
    assert "value='server' checked" in html and "value='standalone' style" in html
    assert "<details><summary>Rules for running on its own" in html
    assert "value='32'" in html and "value='06:00'" in html  # the factory rules
    html = pico.provision.render_setup_page(solo, [], "button")
    assert "value='standalone' checked" in html and "<details open><summary>Rules" in html
    assert " required" not in html  # Wi-Fi may stay empty


def test_portal_saves_standalone_rules(pico, solo):
    portal = pico.provision.Portal(solo, [], "button")
    response = portal.respond(post({"mode": "standalone", "ssid": "", "tz": "UTC", "fan_t": "28",
                                    "fan_h": "60", "heat_t": "12", "w1": "05:30", "w1m": "15",
                                    "w2": "00:00", "w2m": "0"}))
    assert b"run on its own, without Wi-Fi" in response
    assert portal.saved["standalone"] and portal.saved_rules["heater_on_temp_c"][0] == 12.0


def test_portal_keeps_values_after_a_rule_error(pico, solo):
    portal = pico.provision.Portal(solo, [], "button")
    response = portal.respond(post({"mode": "standalone", "ssid": "", "tz": "UTC", "fan_t": "99"}))
    assert portal.saved is None
    assert b"-20 to 60" in response and b"value='99'" in response


def test_server_mode_ignores_the_rules_fields(pico):
    blank = pico.config.load_config("no_such_file.json")
    portal = pico.provision.Portal(blank, [], "new")
    portal.respond(post({"mode": "server", "ssid": "home", "password": "wifi-password", "broker": "10.0.0.2",
                         "port": "1883", "device": "1", "tz": "UTC", "fan_t": "not a number"}))
    assert portal.saved and portal.saved_rules is None


def test_run_setup_standalone_without_wifi(pico, solo, hardware, tmp_path):  # noqa: F811
    fields = {"mode": "standalone", "ssid": "", "tz": "UTC", "fan_t": "28", "fan_h": "60", "heat_t": "12",
              "w1": "05:30", "w1m": "15", "w2": "00:00", "w2m": "0"}
    hardware.install([post(fields)])
    display = RecordingDisplay()
    pico.provision.run_setup(solo, display, "button")
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["standalone"] is True and saved["wifi_ssid"] == ""
    rules = json.loads((tmp_path / "settings.json").read_text())
    assert rules["fan_on_temp_c"] == [28.0, 2.0] and rules["watering"][0] == ["05:30", 15]
    assert not pico.provision.is_unverified()  # nothing to verify without Wi-Fi
    assert "run on its own" in display.messages[-1]
    assert hardware.resets == [True]


# --- the network and controller -----------------------------------------------


def make_net(pico, config, connected=True):
    FakeClient.instances = []
    wlan = FakeWLAN()
    wlan.connected = connected
    return pico.net.Network(config, wlan=wlan, client_factory=FakeClient)


def test_network_never_tries_mqtt(pico, solo, ticks):
    solo["mqtt_broker"] = "10.0.0.2"  # left over from before: still ignored
    net = make_net(pico, solo)
    assert net.server is False
    assert net.connect_mqtt() is False
    for _ in range(5):
        ticks.advance(60_000)
        net.poll(ticks.now)
    net.publish("telemetry", {"x": 1})
    assert FakeClient.instances == [] and net.outbox == []


def test_network_with_a_server(pico, config):
    assert make_net(pico, config).server is True


def controller(pico, config, sensors=None):
    net = make_net(pico, config, connected=bool(config["wifi_ssid"]))
    ctl = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), sensors or FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), net, FakeClock())
    ctl.clock.local_minutes = lambda: 6 * 60 + 5  # 06:05, inside the default watering slot
    ctl.start()
    return ctl


def test_controller_runs_default_rules_at_once(pico, solo):
    cold = FakeSensors()
    cold.dht = (10.0, 45.0)
    ctl = controller(pico, solo, cold)
    ctl.tick()
    assert ctl.local_mode
    assert ctl.relays.state(3) == 1  # heater: below the default 18 °C
    assert ctl.relays.state(1) == 1  # water: 06:00 for 30 minutes
    assert ctl.network_status() == "LOCAL"
    ctl.screen = 0  # the main screen (a relay change shows that relay's screen)
    assert ctl.screen_lines()[3].endswith("LOCAL")
    assert FakeClient.instances == []


def test_controller_uses_rules_from_the_setup_page(pico, solo, tmp_path):
    import local_rules

    rules = local_rules.default_settings()
    rules["heater_on_temp_c"] = [5.0, 1.0]
    local_rules.save_settings(rules)
    cold = FakeSensors()
    cold.dht = (10.0, 45.0)
    ctl = controller(pico, solo, cold)
    ctl.tick()
    assert ctl.relays.state(3) == 0  # 10 °C is warm enough for a 5 °C trigger


def test_standalone_with_wifi_syncs_the_clock(pico, solo):
    solo.update({"wifi_ssid": "home", "wifi_password": "wifi-password"})
    ctl = controller(pico, solo)
    assert ctl.clock.syncs == 1
    assert ctl.network_status() == "LOCAL"
    ctl.net.wlan.connected = False
    assert ctl.network_status() == "NoWiFi LOCAL"


def test_server_controller_without_settings_still_only_enforces_safety(pico, config):
    """Unchanged: with a server, no saved settings means heater and water off, not the defaults."""
    ctl = controller(pico, config)
    assert ctl.settings is None and not ctl.standalone


def test_main_boots_standalone_without_wifi(fake_env, monkeypatch, tmp_path, no_broker):  # noqa: F811
    (tmp_path / "config.json").write_text(json.dumps({"standalone": True, "watchdog": False}))
    fake_env.network.WLAN = FakeWLAN
    controller_module = importlib.import_module("controller")

    class Looping(BaseException):
        pass

    ticks_seen = []

    def tick(self):
        ticks_seen.append(self.network_status())
        raise Looping

    monkeypatch.setattr(controller_module.Controller, "tick", tick)
    with pytest.raises(Looping):
        importlib.import_module("main")
    assert ticks_seen == ["LOCAL"]  # no setup mode, straight into the loop
