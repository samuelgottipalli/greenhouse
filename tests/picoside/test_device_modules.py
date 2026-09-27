"""Tests for picoside/device config, display, relays, sensors and buttons."""
import json

import pytest

from pico_fakes import FakeLcd


# --- config ---------------------------------------------------------------


def test_missing_file_gives_defaults(pico):
    cfg = pico.config.load_config("does_not_exist.json")
    assert cfg == pico.config.DEFAULTS
    assert "No Wi-Fi SSID set" in pico.config.config_problems(cfg)


def test_file_values_override_defaults(pico, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"wifi_ssid": "net", "publish_interval_s": 60}))
    cfg = pico.config.load_config(str(path))
    assert cfg["wifi_ssid"] == "net" and cfg["publish_interval_s"] == 60
    assert cfg["relay_pins"] == pico.config.DEFAULTS["relay_pins"]


def test_legacy_config_is_upgraded(pico, tmp_path):
    legacy = {f"relay{n}_pin": 10 + n for n in range(1, 9)}
    legacy.update({f"button_relay{n}_pin": 30 + n for n in range(1, 5)})
    legacy.update({"timezone_offset": -8, "gps_tx_pin": 4, "gps_rx_pin": 5,
                   "mqtt_topic_publish": "greenhouse/data", "wifi_ssid": "net"})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(legacy))
    cfg = pico.config.load_config(str(path))
    assert cfg["relay_pins"] == [11, 12, 13, 14, 15, 16, 17, 18]
    assert cfg["button_relay_pins"] == [31, 32, 33, 34]
    assert cfg["utc_offset_minutes"] == -480
    assert not {"gps_tx_pin", "timezone_offset", "relay1_pin", "mqtt_topic_publish"} & set(cfg)


def test_placeholder_broker_is_a_problem(pico, config):
    assert pico.config.config_problems(config) == []
    config["mqtt_broker"] = "YOUR_MQTT_BROKER"
    assert pico.config.config_problems(config) == ["No MQTT broker set"]


def test_example_config_is_complete(pico):
    from support import PICO_DIR

    example = json.loads((PICO_DIR / "config.example.json").read_text())
    assert set(example) == set(pico.config.DEFAULTS)


# --- display --------------------------------------------------------------


@pytest.fixture
def display(pico, config):
    return pico.display.Display(config, lcd=FakeLcd())


def test_fit_and_wrap(pico):
    assert pico.display.fit("abc") == "abc" + " " * 17
    assert pico.display.fit("x" * 25) == "x" * 20
    assert pico.display.wrap("A" * 20 + "B" * 5) == ["A" * 20, "B" * 5 + " " * 15, " " * 20, " " * 20]


def test_show_lines_only_rewrites_changed_lines(display):
    display.show_lines(["one", "two", "three", "four"])
    assert display.lcd.writes == 4
    display.show_lines(["one", "TWO", "three", "four"])
    assert display.lcd.writes == 5
    assert display.lcd.screen[1] == "TWO" + " " * 17


def test_shorter_text_clears_old_characters(display):
    display.show_lines(["Temp: 21.5C"])
    display.show_lines(["Temp: --"])
    assert display.lcd.screen[0] == "Temp: --" + " " * 12


def test_clear_then_same_text_is_redrawn(display):
    display.show_lines(["hello"])
    display.clear()
    display.show_lines(["hello"])
    assert display.lcd.screen[0].startswith("hello")


def test_default_driver_is_created(pico, config):
    assert isinstance(pico.display.Display(config).lcd, FakeLcd)


# --- relays ---------------------------------------------------------------


def test_relays_start_off(pico, config):
    relays = pico.relays.Relays(config)
    assert relays.states() == [0] * 8
    assert [p.value() for p in relays.pins] == [0] * 8


def test_set_and_toggle(pico, config):
    relays = pico.relays.Relays(config)
    assert relays.set(3, 1) is True
    assert relays.set(3, 1) is False
    assert relays.pins[2].value() == 1
    assert relays.toggle(3) == 0 and relays.pins[2].value() == 0
    assert relays.name(2) == "fan"


def test_active_low_board(pico, config):
    config["relay_active_low"] = True
    relays = pico.relays.Relays(config)
    assert [p.value() for p in relays.pins] == [1] * 8  # all off
    relays.set(1, 1)
    assert relays.pins[0].value() == 0


@pytest.mark.parametrize("value, ok", [(1, True), (8, True), (0, False), (9, False), ("2", False), (True, False), (2.0, False)])
def test_valid_relay_numbers(pico, value, ok):
    assert pico.relays.Relays.valid(value) is ok


# --- sensors --------------------------------------------------------------


def test_sensors(pico, config):
    sensors = pico.sensors.Sensors(config)
    assert sensors.read_dht() == (21.5, 45.0)
    assert sensors.read_ldr() == 12345
    sensors.dht_sensor.fail = True
    assert sensors.read_dht() == (None, None)


# --- buttons --------------------------------------------------------------


def test_button_irqs_record_events(pico, config, ticks):
    buttons = pico.buttons.Buttons(config)
    buttons.pins[2].handler(buttons.pins[2])
    ticks.advance(10)
    buttons.pins[2].handler(buttons.pins[2])  # bounce, ignored
    ticks.advance(100)
    buttons.pins[0].handler(buttons.pins[0])
    events = buttons.take_events()
    assert [i for i, _ in events] == [2, 0]
    assert buttons.take_events() == []


def test_event_queue_is_bounded(pico, config, ticks):
    buttons = pico.buttons.Buttons(config)
    for _ in range(40):
        ticks.advance(100)
        buttons.pins[1].handler(buttons.pins[1])
    assert len(buttons.take_events()) == pico.buttons.MAX_EVENTS


def test_is_pressed_reads_active_low(pico, config):
    buttons = pico.buttons.Buttons(config)
    assert not buttons.is_pressed(1)
    buttons.pins[1].value(0)
    assert buttons.is_pressed(1)


def test_ping_must_be_shorter_than_keepalive(pico, config):
    config["mqtt_ping_s"] = config["mqtt_keepalive_s"]
    assert "Ping must be < keepalive" in pico.config.config_problems(config)


def test_low_power_defaults(pico):
    d = pico.config.DEFAULTS
    assert (d["mqtt_keepalive_s"], d["mqtt_ping_s"]) == (300, 120)
    assert d["wifi_power_save"] is True and d["backlight_timeout_s"] == 60
