"""
Simulated 7-day soak test of the controller (PLAN 3.2).

Runs the real Controller and Network code (only the MQTT client, Wi-Fi radio
and sensors are fakes) for 7 simulated days in 5-second steps, with a
30-minute Wi-Fi outage every day and a daily temperature cycle that crosses
the heater trigger. The on-hardware soak is still a RUNBOOK sign-off item.
"""
import json

from pico_fakes import FakeLcd, FakeWLAN
from test_controller import FakeButtons, FakeClock
from test_net import FakeClient

STEP_MS = 5_000
DAY_MS = 24 * 3600 * 1000
OUTAGE_START_MS = 3 * 3600 * 1000     # 03:00 each day
OUTAGE_MS = 30 * 60 * 1000
SETTINGS = {
    "fan_on_temp_c": [30.0, 2.0],
    "fan_on_humidity_pct": [90.0, 5.0],
    "heater_on_temp_c": [10.0, 2.0],
    "watering": [["00:00", 0]],
}


class CyclingSensors:
    """Temperature swings 6-18 C over each day; humidity steady."""

    def __init__(self, ticks):
        self.ticks = ticks
        self.start = ticks.now

    def temperature(self):
        phase = ((self.ticks.now - self.start) % DAY_MS) / DAY_MS
        return 6.0 + 12.0 * (1 - abs(2 * phase - 1))

    def read_dht(self):
        return round(self.temperature(), 1), 50.0

    def read_ldr(self):
        return 20000


class ClockWithMinutes(FakeClock):
    def local_minutes(self):
        return 720


def test_seven_day_soak(pico, config, ticks):
    FakeClient.instances = []
    FakeClient.fail_connect = False
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan, client_factory=FakeClient)
    sensors = CyclingSensors(ticks)
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), sensors,
        pico.relays.Relays(config), FakeButtons(), net, ClockWithMinutes(),
    )
    controller.start()
    controller.handle_settings(SETTINGS)
    ticks.now = 2 ** 30 - 3_600_000  # cross the ticks wrap during the run
    controller._last_tick = ticks.now

    local_mode_spells, was_local = 0, False
    max_outbox = 0
    heater_mistakes = 0
    elapsed = 0
    while elapsed < 7 * DAY_MS:
        in_outage = OUTAGE_START_MS <= elapsed % DAY_MS < OUTAGE_START_MS + OUTAGE_MS
        wlan.connected = wlan.connected and not in_outage
        wlan.connect_succeeds = not in_outage
        controller.tick()
        if controller.local_mode and not was_local:
            local_mode_spells += 1
        was_local = controller.local_mode
        max_outbox = max(max_outbox, len(net.outbox))
        # While the device is in charge (local mode) the heater must never be on
        # well above trigger + buffer (12 C). Online, the server's automation
        # decides, and there is no server in this simulation.
        if controller.local_mode and controller.relays.state(3) and sensors.temperature() > 12.5:
            heater_mistakes += 1
        ticks.advance(STEP_MS)
        elapsed += STEP_MS

    telemetry = [json.loads(body) for c in FakeClient.instances for topic, body, _ in c.published
                 if topic.endswith("/telemetry")]
    uptimes = [t["uptime_s"] for t in telemetry]

    assert local_mode_spells == 7                       # one per daily outage
    assert max_outbox <= pico.net.OUTBOX_MAX            # queue stays bounded
    assert net.mqtt_ok and not controller.local_mode    # recovered at the end
    assert len(telemetry) == 7 * 288                    # every 5-min report delivered, none lost
    assert uptimes == sorted(uptimes) and len(set(uptimes)) == len(uptimes)  # each exactly once, in order
    assert abs(controller.uptime_ms - 7 * DAY_MS) <= STEP_MS  # uptime right across the ticks wrap
    assert heater_mistakes == 0
    heater_changes = [json.loads(b)["state"] for c in FakeClient.instances for t, b, _ in c.published
                      if t.endswith("relay/3/state")]
    assert heater_changes.count(1) >= 7                 # heater cycled on every cold night
