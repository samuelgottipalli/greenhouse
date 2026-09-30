"""Tests for picoside/device/controller.py (the main loop) with fake parts."""
import pytest

from pico_fakes import FakeLcd


class FakeSensors:
    def __init__(self):
        self.dht = (21.5, 45.0)
        self.reads = 0

    def read_dht(self):
        self.reads += 1
        return self.dht

    def read_ldr(self):
        return 30000


class FakeButtons:
    def __init__(self):
        self.events = []
        self.held = set()

    def take_events(self):
        events, self.events = self.events, []
        return events

    def is_pressed(self, index):
        return index in self.held


class FakeNet:
    def __init__(self):
        self.wifi_ok = True
        self.mqtt_ok = True
        self.published = []
        self.polls = 0
        self.on_command = None
        self.wifi_result = True
        self.mqtt_result = True

    def connect_wifi(self):
        self.wifi_ok = self.wifi_result
        return self.wifi_result

    def connect_mqtt(self):
        self.mqtt_ok = self.mqtt_result
        return self.mqtt_result

    def poll(self, now):
        self.polls += 1

    def publish(self, suffix, payload, retain=False):
        self.published.append((suffix, payload, retain))

    def flush(self):
        self.flushed = getattr(self, "flushed", 0) + 1
        return 0

    def ip_address(self):
        return "192.168.1.50" if self.wifi_ok else None

    def rssi(self):
        return -61 if self.wifi_ok else None

    def of(self, suffix):
        return [p for s, p, _ in self.published if s == suffix]


class FakeClock:
    def __init__(self):
        self.synced = False
        self.sync_ok = True
        self.syncs = 0
        self.set = True

    def sync(self):
        self.syncs += 1
        self.synced = self.synced or self.sync_ok
        return self.sync_ok

    def utc_str(self):
        return "2026-09-26 19:00:00" if self.set else None

    def local_str(self):
        return "2026-09-26 12:00:00" if self.set else None


@pytest.fixture
def ctl(pico, config, ticks):
    display = pico.display.Display(config, lcd=FakeLcd())
    controller = pico.controller.Controller(
        config, display, FakeSensors(), pico.relays.Relays(config), FakeButtons(), FakeNet(), FakeClock()
    )
    controller.start()
    return controller


def press(ctl, button, ticks, gap=0):
    ticks.advance(gap)
    ctl.buttons.events.append((button, ticks.now))


def run_for(ctl, ticks, ms, step=50):
    for _ in range(ms // step):
        ticks.advance(step)
        ctl.tick()


# --- boot -----------------------------------------------------------------


def test_start_connects_everything(ctl):
    assert ctl.clock.syncs == 1
    assert ctl.net.on_command == ctl.handle_command
    assert ctl.display.lcd.screen == [" " * 20] * 4


def test_start_without_wifi_skips_clock_and_mqtt(pico, config):
    net = FakeNet()
    net.wifi_result = False
    clock = FakeClock()
    lcd = FakeLcd()
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=lcd), FakeSensors(), pico.relays.Relays(config),
        FakeButtons(), net, clock,
    )
    controller.start()
    assert clock.syncs == 0


# --- periodic work --------------------------------------------------------


def test_first_tick_reads_and_publishes(ctl):
    ctl.tick()
    assert ctl.sensors.reads == 1
    (telemetry,) = ctl.net.of("telemetry")
    assert telemetry == {
        "device_id": 1, "ts_utc": "2026-09-26 19:00:00", "temperature_c": 21.5,
        "humidity_pct": 45.0, "light_raw": 30000, "relays": [0] * 8, "uptime_s": 0, "mem_free": None, "rssi_dbm": -61,
    }


def test_free_memory_is_measured_after_a_collection(ctl, pico, monkeypatch):
    """Found on the Pico: without gc.collect() the dashboard showed ~47 KB free instead of ~140 KB."""
    calls = []
    fake_gc = type("FakeGC", (), {
        "collect": staticmethod(lambda: calls.append("collect")),
        "mem_free": staticmethod(lambda: calls.append("mem_free") or 143984),
    })
    monkeypatch.setattr(pico.controller, "gc", fake_gc)
    ctl.tick()
    (telemetry,) = ctl.net.of("telemetry")
    assert telemetry["mem_free"] == 143984 and calls == ["collect", "mem_free"]


def test_intervals(ctl, ticks):
    ctl.tick()
    run_for(ctl, ticks, 59_950)
    assert ctl.sensors.reads == 1
    run_for(ctl, ticks, 100)
    assert ctl.sensors.reads == 2
    run_for(ctl, ticks, 300_000)
    assert len(ctl.net.of("telemetry")) == 2
    assert ctl.net.polls > 6000


def test_failed_dht_read_keeps_last_values(ctl, ticks):
    ctl.tick()
    ctl.sensors.dht = (None, None)
    run_for(ctl, ticks, 30_050)
    assert (ctl.temperature, ctl.humidity) == (21.5, 45.0)


def test_uptime_survives_ticks_wrap(ctl, ticks):
    ticks.now = 2 ** 30 - 1000
    ctl._last_tick = ticks.now
    run_for(ctl, ticks, 5000)
    assert 4900 <= ctl.uptime_ms <= 5100


def test_ntp_retries_until_first_success_then_daily(ctl, ticks):
    ctl.clock.synced = False
    ctl.clock.sync_ok = False
    ctl._last_ntp = None
    ctl.tick()
    assert ctl.clock.syncs == 2
    run_for(ctl, ticks, 5 * 60 * 1000, step=1000)
    assert ctl.clock.syncs == 3
    ctl.clock.sync_ok = True
    run_for(ctl, ticks, 5 * 60 * 1000, step=1000)
    assert ctl.clock.syncs == 4
    run_for(ctl, ticks, 60 * 60 * 1000, step=10_000)
    assert ctl.clock.syncs == 4  # next one due after 24 h


def test_no_ntp_attempt_without_wifi(ctl, ticks):
    ctl.net.wifi_ok = False
    ctl._last_ntp = None
    ctl.tick()
    assert ctl.clock.syncs == 1


# --- commands -------------------------------------------------------------


def test_command_switches_relay_and_publishes_state(ctl):
    assert ctl.handle_command({"relay": 2, "state": 1, "source": "auto"}) is True
    assert ctl.relays.state(2) == 1
    assert ctl.net.published[-1] == ("relay/2/state", {
        "device_id": 1, "relay": 2, "state": 1, "source": "auto", "ts_utc": "2026-09-26 19:00:00",
    }, True)
    assert ctl.screen == 2


def test_command_without_source_defaults_to_web(ctl):
    ctl.handle_command({"relay": 1, "state": 1})
    assert ctl.net.published[-1][1]["source"] == "web"


@pytest.mark.parametrize(
    "command",
    [{}, {"relay": 9, "state": 1}, {"relay": "2", "state": 1}, {"relay": 2, "state": 2},
     {"relay": 2, "state": True}, {"relay": 2}],
)
def test_invalid_commands_are_ignored(ctl, command):
    assert ctl.handle_command(command) is False
    assert ctl.relays.states() == [0] * 8
    assert ctl.net.published == []


# --- buttons --------------------------------------------------------------


def test_single_press_waits_for_double_press_window(ctl, ticks):
    press(ctl, 2, ticks)
    ctl.tick()
    assert ctl.relays.state(2) == 0
    run_for(ctl, ticks, 450)
    assert ctl.relays.state(2) == 1
    assert ctl.net.published[-1][1]["source"] == "device"


def test_double_press_toggles_paired_relay_only(ctl, ticks):
    press(ctl, 1, ticks)
    ctl.tick()
    press(ctl, 1, ticks, gap=200)
    run_for(ctl, ticks, 600)
    assert ctl.relays.state(1) == 0
    assert ctl.relays.state(5) == 1


def test_slow_second_press_is_two_single_presses(ctl, ticks):
    press(ctl, 3, ticks)
    run_for(ctl, ticks, 500)
    press(ctl, 3, ticks)
    run_for(ctl, ticks, 500)
    assert ctl.relays.state(3) == 0
    assert [p["source"] for p in ctl.net.of("relay/3/state")].count("device") == 2


def test_held_button_waits_for_release(ctl, ticks):
    press(ctl, 4, ticks)
    ctl.buttons.held.add(4)
    run_for(ctl, ticks, 1000)
    assert ctl.relays.state(4) == 0
    ctl.buttons.held.discard(4)
    run_for(ctl, ticks, 100)
    assert ctl.relays.state(4) == 1


def test_screen_button_with_button_1_shows_ip_without_toggling(ctl, ticks):
    press(ctl, 1, ticks)
    ctl.buttons.held.add(1)
    ctl.tick()
    press(ctl, 0, ticks, gap=300)
    ctl.tick()
    ctl.buttons.held.discard(1)
    run_for(ctl, ticks, 1000)
    assert ctl.screen == ctl_module(ctl).SCREEN_IP
    assert ctl.relays.state(1) == 0
    assert ctl.display.lcd.screen[1].startswith("192.168.1.50")


def test_screen_button_cycles_and_times_out(ctl, ticks):
    screens = []
    for _ in range(10):
        press(ctl, 0, ticks, gap=100)
        ctl.tick()
        screens.append(ctl.screen)
    assert screens == [1, 2, 3, 4, 5, 6, 7, 8, 0, 1]
    run_for(ctl, ticks, 10_100)
    assert ctl.screen == 0


def ctl_module(ctl):
    import sys

    return sys.modules[type(ctl).__module__]


# --- screen content -------------------------------------------------------


def test_main_screen(ctl, ticks):
    ctl.tick()
    assert ctl.display.lcd.screen == [
        "2026-09-26 12:00:00 ",
        "Temp: 21.5C         ",
        "Hum:  45.0%         ",
        "Up   0s OK          ",
    ]


def test_main_screen_before_first_reading_and_offline(ctl):
    ctl.clock.set = False
    ctl.net.mqtt_ok = False
    ctl.net.wifi_ok = False
    ctl.sensors.dht = (None, None)
    ctl.tick()
    assert [line.rstrip() for line in ctl.display.lcd.screen] == [
        "Clock not set", "Temp: --", "Hum:  --", "Up   0s NoWiFi",
    ]


def test_relay_screen(ctl):
    ctl.handle_command({"relay": 3, "state": 1})
    ctl.tick()
    assert [line.rstrip() for line in ctl.display.lcd.screen[:2]] == ["Relay 3: heater", "State: On"]


def test_network_status(ctl):
    assert ctl.network_status() == "OK"
    ctl.net.mqtt_ok = False
    assert ctl.network_status() == "NoMQTT"


# --- state resync (P-14) ------------------------------------------------------

def states_published(ctl):
    return [(p["relay"], p["state"], p["source"]) for s, p, _ in ctl.net.published if s.startswith("relay/")]


def test_all_states_published_when_link_comes_up(ctl):
    ctl.tick()
    assert states_published(ctl) == [(n, 0, "auto") for n in range(1, 9)]
    ctl.net.published.clear()
    ctl.tick()
    assert states_published(ctl) == []  # only on the transition


def test_states_republished_after_reconnect(ctl):
    ctl.tick()
    ctl.handle_command({"relay": 2, "state": 1})
    ctl.net.mqtt_ok = False
    ctl.tick()
    ctl.net.published.clear()
    ctl.net.mqtt_ok = True
    ctl.tick()
    assert (2, 1, "auto") in states_published(ctl)
    assert len(states_published(ctl)) == 8


def test_no_state_burst_while_offline(ctl):
    ctl.net.mqtt_ok = False
    ctl.tick()
    assert states_published(ctl) == []


# --- backlight (power saving) --------------------------------------------------------

def test_backlight_turns_off_after_timeout(ctl, ticks):
    run_for(ctl, ticks, 59_000)
    assert ctl.display.backlight and ctl.display.lcd.lit
    run_for(ctl, ticks, 2_000)
    assert not ctl.display.backlight and not ctl.display.lcd.lit


def test_first_press_only_wakes_the_screen(ctl, ticks):
    run_for(ctl, ticks, 61_000)
    press(ctl, 2, ticks)
    run_for(ctl, ticks, 600)
    assert ctl.display.backlight
    assert ctl.relays.state(2) == 0  # the waking press is not a command
    press(ctl, 2, ticks)
    run_for(ctl, ticks, 600)
    assert ctl.relays.state(2) == 1


def test_presses_keep_the_backlight_on(ctl, ticks):
    for _ in range(3):
        run_for(ctl, ticks, 50_000)
        press(ctl, 0, ticks)
        ctl.tick()
    assert ctl.display.backlight


def test_backlight_timeout_zero_keeps_it_on(pico, config, ticks):
    config["backlight_timeout_s"] = 0
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), FakeNet(), FakeClock(),
    )
    controller.start()
    run_for(controller, ticks, 10 * 60 * 1000, step=1000)
    assert controller.display.backlight


def test_remote_command_does_not_wake_the_backlight(ctl, ticks):
    run_for(ctl, ticks, 61_000)
    ctl.handle_command({"relay": 2, "state": 1})
    ctl.tick()
    assert not ctl.display.backlight
    assert ctl.display.lcd.screen[0].startswith("Relay 2: fan")  # text still updates


# --- restart from the dashboard (Settings › System) ------------------------------------


def test_restart_command_restarts_on_the_next_tick(pico, config, ticks):
    resets = []
    lcd = FakeLcd()
    display = pico.display.Display(config, lcd=lcd)
    net = FakeNet()
    controller = pico.controller.Controller(config, display, FakeSensors(), pico.relays.Relays(config),
                                            FakeButtons(), net, FakeClock(), reset=lambda: resets.append(True))
    controller.start()
    assert controller.handle_command({"action": "restart", "source": "web"}) is True
    assert resets == []  # not inside the MQTT callback
    controller.tick()
    assert resets == [True] and net.flushed == 1  # queued messages went out first
    assert "Restarting" in "".join(lcd.screen)


def test_unknown_action_is_ignored(ctl):
    assert ctl.handle_command({"action": "format-the-disk"}) is False
    assert ctl.restart_requested is False
