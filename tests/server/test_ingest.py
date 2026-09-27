"""Tests for server/services/ingest.py and the db functions it uses (S-01)."""
import json
from types import SimpleNamespace

import pytest

from core import db
from services import ingest

NOW = "2026-09-26 19:00:00"


def telemetry(**overrides):
    body = {"device_id": 1, "ts_utc": "2026-09-26 18:55:00", "temperature_c": 22.5,
            "humidity_pct": 48.0, "light_raw": 30000, "relays": [0] * 8, "uptime_s": 10}
    body.update(overrides)
    return json.dumps(body).encode()


def state(relay_state, source="device", ts="2026-09-26 18:56:00"):
    return json.dumps({"device_id": 1, "relay": 2, "state": relay_state, "source": source, "ts_utc": ts}).encode()


def test_telemetry_is_stored(seeded_db, db_conn):
    message = ingest.handle_message("greenhouse/1/telemetry", telemetry(), NOW)
    assert message == "telemetry from 1: 3 new readings"
    rows = db_conn.execute(
        "SELECT m.name, r.value FROM sensor_readings r JOIN measures m USING (measure_id) "
        "WHERE reading_utc = '2026-09-26 18:55:00' ORDER BY m.name"
    ).fetchall()
    assert rows == [("humidity", 48.0), ("light_raw", 30000.0), ("temperature", 22.5)]
    latest = db.latest_sensor_readings().set_index("measure")
    assert latest.loc["temperature", "value"] == 22.5


def test_replayed_telemetry_is_ignored(seeded_db):
    ingest.handle_message("greenhouse/1/telemetry", telemetry(), NOW)
    assert ingest.handle_message("greenhouse/1/telemetry", telemetry(), NOW).endswith(": 0 new readings")


def test_clock_not_set_uses_arrival_time(seeded_db, db_conn):
    ingest.handle_message("greenhouse/1/telemetry", telemetry(ts_utc=None), NOW)
    assert db_conn.execute("SELECT count(*) FROM sensor_readings WHERE reading_utc = ?", (NOW,)).fetchone() == (3,)


@pytest.mark.parametrize("bad_ts", ["2026-09-26T18:55:00Z", "yesterday", 12345])
def test_malformed_timestamp_uses_arrival_time(seeded_db, db_conn, bad_ts):
    ingest.handle_message("greenhouse/1/telemetry", telemetry(ts_utc=bad_ts), NOW)
    assert db_conn.execute("SELECT count(*) FROM sensor_readings WHERE reading_utc = ?", (NOW,)).fetchone() == (3,)


def test_missing_sensor_values_are_skipped(seeded_db):
    message = ingest.handle_message("greenhouse/1/telemetry", telemetry(temperature_c=None, humidity_pct=True), NOW)
    assert message.endswith(": 1 new readings")


def test_unknown_device_is_reported_not_raised(seeded_db):
    assert ingest.handle_message("greenhouse/9/telemetry", telemetry(), NOW).endswith(": None new readings")


def test_device_button_change_is_logged(seeded_db):
    # Fixture: fan (relay 2) last logged on.
    assert ingest.handle_message("greenhouse/1/relay/2/state", state(0), NOW).endswith("logged")
    fan = db.latest_relay_states().set_index("relay_id").loc[2]
    assert (fan["state"], fan["source"], fan["event_utc"]) == (0, "device", "2026-09-26 18:56:00")


def test_echo_of_logged_command_is_not_duplicated(seeded_db, db_conn):
    before = db_conn.execute("SELECT count(*) FROM relay_events").fetchone()
    assert ingest.handle_message("greenhouse/1/relay/2/state", state(1, source="web"), NOW).endswith("unchanged")
    assert db_conn.execute("SELECT count(*) FROM relay_events").fetchone() == before


def test_unknown_source_becomes_device(seeded_db):
    ingest.handle_message("greenhouse/1/relay/2/state", state(0, source="gremlin"), NOW)
    assert db.latest_relay_states().set_index("relay_id").loc[2, "source"] == "device"


@pytest.mark.parametrize("bad", [2, True, "1", None])
def test_bad_relay_state_is_ignored(seeded_db, bad):
    assert ingest.handle_message("greenhouse/1/relay/2/state", state(bad), NOW).startswith("ignored bad state")


def test_status_is_stored(seeded_db):
    assert ingest.handle_message("greenhouse/1/status", b"offline", NOW) == "device 1 offline"
    status = db.device_status()
    assert (status["status"], status["updated_utc"], status["uptime_s"]) == ("offline", NOW, None)
    ingest.handle_message("greenhouse/1/status", b"online", "2026-09-26 19:05:00")
    assert db.device_status()["status"] == "online"


@pytest.mark.parametrize(
    "topic, payload",
    [
        ("other/1/telemetry", b"{}"),
        ("greenhouse/x/telemetry", b"{}"),
        ("greenhouse/1/unknown", b"{}"),
        ("greenhouse/1/telemetry", b"not json"),
        ("greenhouse/1/telemetry", b"[1, 2]"),
        ("greenhouse/1/status", b"maybe"),
        ("greenhouse", b"{}"),
    ],
)
def test_bad_messages_are_ignored(seeded_db, topic, payload):
    assert ingest.handle_message(topic, payload, NOW).startswith("ignored")


def test_subscriptions():
    assert ingest.subscriptions("gh") == ["gh/+/telemetry", "gh/+/relay/+/state", "gh/+/status", "gh/+/firmware"]


def test_client_wiring(seeded_db, monkeypatch):
    client = ingest.make_client()
    subscribed = []
    monkeypatch.setattr(client, "subscribe", lambda topic, qos: subscribed.append((topic, qos)))
    client.on_connect(client, None, None, 0, None)
    assert [t for t, _ in subscribed] == ingest.subscriptions()
    client.on_message(client, None, SimpleNamespace(topic="greenhouse/1/status", payload=b"online"))
    assert db.device_status()["status"] == "online"
    # A handler error is logged, not raised into the network loop.
    monkeypatch.setattr(ingest, "handle_message", lambda *a: 1 / 0)
    client.on_message(client, None, SimpleNamespace(topic="t", payload=b""))


def test_client_uses_credentials(monkeypatch):
    from core import settings

    monkeypatch.setattr(settings, "MQTT_USERNAME", "server")
    monkeypatch.setattr(settings, "MQTT_PASSWORD", "pw")
    client = ingest.make_client()
    assert client._username == b"server"


def test_insert_sensor_readings_unknown_measure(seeded_db):
    assert db.insert_sensor_readings({"pressure_x": 1.0}, NOW) is None


def test_preferences_round_trip(seeded_db):
    assert db.read_preferences() == {}
    assert db.save_preferences({"units": "SI", "time_format": "24-hour"})
    db.save_preferences({"units": "US"})
    assert db.read_preferences() == {"units": "US", "time_format": "24-hour"}
