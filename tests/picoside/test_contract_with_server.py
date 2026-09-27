"""
End-to-end contract tests for docs/MQTT.md: messages produced by the real
firmware code are consumed by the real server code, and vice versa, with only
the broker replaced.
"""
import json

import pytest

from pico_fakes import FakeLcd, FakeWLAN
from test_controller import FakeButtons, FakeClock, FakeSensors
from test_net import FakeClient

from core import db, mqtt
from services import ingest


@pytest.fixture
def device(pico, config, seeded_db):
    FakeClient.instances = []
    FakeClient.fail_connect = False
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan, client_factory=FakeClient)
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), net, FakeClock(),
    )
    controller.start()
    return controller


def deliver_to_server(device):
    """Feed everything the device published to the ingest service."""
    results = []
    for topic, body, _retain in FakeClient.instances[-1].published:
        payload = body.encode() if isinstance(body, str) else body
        results.append(ingest.handle_message(topic, payload, "2026-09-26 19:00:00"))
    FakeClient.instances[-1].published.clear()
    return results


def test_status_and_telemetry_reach_the_database(device):
    device.tick()
    results = deliver_to_server(device)
    assert "device 1 online" in results
    assert any(r.startswith("telemetry from 1: 3 new") for r in results)
    latest = db.latest_sensor_readings().set_index("measure")
    assert latest.loc["temperature", "value"] == 21.5
    assert latest.loc["temperature", "reading_utc"] == "2026-09-26 19:00:00"
    assert db.device_status()["status"] == "online"


def test_server_command_switches_device_relay_and_state_is_logged(device, monkeypatch):
    sent = []
    monkeypatch.setattr(mqtt, "single", lambda **kw: sent.append(kw))
    mqtt.publish_relay_command(relay_id=3, state=1, source="web")
    (message,) = sent

    # The broker delivers the server's message to the device's subscription.
    assert message["topic"] == FakeClient.instances[-1].calls[3][1]  # subscribed topic
    FakeClient.instances[-1].incoming.append(message["payload"].encode())
    device.tick()
    assert device.relays.state(3) == 1

    deliver_to_server(device)
    heater = db.latest_relay_states().set_index("relay_id").loc[3]
    assert (heater["state"], heater["source"]) == (1, "web")


def test_device_button_change_reaches_the_database(device, ticks):
    device.buttons.events.append((4, ticks.now))
    for _ in range(12):
        ticks.advance(50)
        device.tick()
    assert device.relays.state(4) == 1
    deliver_to_server(device)
    light = db.latest_relay_states().set_index("relay_id").loc[4]
    assert (light["state"], light["source"]) == (1, "device")


def test_every_device_payload_field_is_documented(device):
    device.tick()
    device.handle_command({"relay": 1, "state": 1})
    docs = (pytest.importorskip("support").REPO_ROOT / "docs" / "MQTT.md").read_text(encoding="utf-8")
    for topic, body, _ in FakeClient.instances[-1].published:
        if body in ("online", "offline"):
            continue
        for field in json.loads(body):
            assert f'"{field}"' in docs, (topic, field)


def test_reboot_resets_server_view_of_relays(device):
    # P-14: fixture log says the fan is on; a freshly booted device has it off.
    assert db.latest_relay_states().set_index("relay_id").loc[2, "state"] == 1
    device.tick()
    deliver_to_server(device)
    fan = db.latest_relay_states().set_index("relay_id").loc[2]
    assert (fan["state"], fan["source"]) == (0, "auto")
    # Relays that already matched the log were not logged again.
    heater = db.latest_relay_states().set_index("relay_id").loc[3]
    assert heater["event_utc"] == "2025-10-27 01:00:00"


def test_server_settings_are_accepted_by_device(device, monkeypatch):
    # P-15: the retained settings message the server publishes is what local mode needs.
    from core.automation import device_settings

    sent = []
    monkeypatch.setattr(mqtt, "single", lambda **kw: sent.append(kw))
    thresholds = db.read_thresholds().set_index("name")
    limits = {name: (row.value, row.buffer) for name, row in thresholds.iterrows()}
    schedule = db.read_watering_schedule()
    slots = list(zip(schedule["start_local"], schedule["duration_min"].astype(int)))
    assert mqtt.publish_device_settings(device_settings(limits, slots))
    (message,) = sent
    assert message["retain"] is True
    assert ("subscribe", message["topic"]) in FakeClient.instances[-1].calls
    FakeClient.instances[-1].incoming.append((message["topic"].encode(), message["payload"].encode()))
    device.tick()
    assert device.settings["heater_on_temp_c"] == [18.0, 2.0]
    assert device.settings["watering"][0] == ["06:00", 30]
