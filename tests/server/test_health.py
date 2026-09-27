"""Tests for service and device health (PLAN 3.3, 4.2): core/health.py and its users."""
import json
import socket
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from core import db, health
from core.timeutil import utc_timestamp
from support import SERVER_DIR


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# --- Heartbeat -----------------------------------------------------------------

def test_heartbeat_throttles_writes(seeded_db):
    clock = Clock()
    hb = health.Heartbeat("automation", every_s=30, clock=clock)
    assert hb.beat() is True
    clock.t += 10
    assert hb.beat() is False
    clock.t += 25
    assert hb.beat() is True
    assert db.read_heartbeats().set_index("service").loc["automation", "healthy"] == 1


def test_heartbeat_writes_immediately_on_change(seeded_db):
    clock = Clock()
    hb = health.Heartbeat("ingest", clock=clock)
    hb.beat(True, "connected")
    clock.t += 1
    assert hb.beat(False, "broker unreachable") is True
    row = db.read_heartbeats().set_index("service").loc["ingest"]
    assert (row["healthy"], row["detail"]) == (0, "broker unreachable")


def test_sd_notify_outside_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert health.sd_notify("WATCHDOG=1") is False


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX") or sys.platform == "win32", reason="Unix datagram sockets")
def test_sd_notify_reaches_systemd_socket(monkeypatch, tmp_path):
    path = str(tmp_path / "notify.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(path)
    try:
        monkeypatch.setenv("NOTIFY_SOCKET", path)
        assert health.sd_notify("WATCHDOG=1") is True
        assert server.recv(64) == b"WATCHDOG=1"
    finally:
        server.close()


# --- service_health -----------------------------------------------------------------

NOW = datetime(2026, 9, 26, 19, 0, tzinfo=timezone.utc)


def test_service_health_statuses(seeded_db):
    db.record_heartbeat("ingest", True, "connected", updated_utc=utc_timestamp(NOW - timedelta(seconds=20)))
    db.record_heartbeat("automation", False, "db locked", updated_utc=utc_timestamp(NOW - timedelta(seconds=20)))
    db.record_heartbeat("weather", True, "", updated_utc=utc_timestamp(NOW - timedelta(minutes=10)))
    status = {e["service"]: e["status"] for e in health.service_health(NOW)}
    assert status == {"ingest": "ok", "automation": "degraded", "weather": "down", "firmware": "unknown"}


def test_service_health_unknown(seeded_db):
    assert [e["status"] for e in health.service_health(NOW)] == ["unknown"] * 4


@pytest.mark.parametrize("rssi, text", [(-50, "good"), (-60, "good"), (-70, "fair"), (-80, "weak"), (None, "unknown")])
def test_signal_quality(rssi, text):
    assert health.signal_quality(rssi) == text


@pytest.mark.parametrize("seconds, text", [(45, "45 s"), (720, "12 min"), (18180, "5 h 3 min"), (273600, "3 d 4 h"), (None, "?")])
def test_format_duration(seconds, text):
    assert health.format_duration(seconds) == text


# --- services beat -----------------------------------------------------------------

class Recorder:
    def __init__(self):
        self.beats = []

    def beat(self, healthy=True, detail=""):
        self.beats.append((healthy, detail))


def test_automation_beats_only_after_good_passes(seeded_db, monkeypatch):
    from services import automation

    results = iter([[], RuntimeError("db locked"), []])

    def run_once(device_id=1):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(automation, "run_once", run_once)
    hb = Recorder()
    automation.main(pause=lambda s: None, max_passes=3, heartbeat=hb)
    assert hb.beats == [(True, "1 devices, 0 changes last pass")] * 2


def test_weather_heartbeat_reflects_last_slot(monkeypatch):
    from services import weather_collector

    results = iter([False, False])
    monkeypatch.setattr(weather_collector, "collect_once", lambda: next(results))
    hb = Recorder()
    clock = SimpleNamespace(now=datetime(2026, 9, 26, 10, 0, 5))
    weather_collector.run(now=lambda: clock.now, pause=lambda s: None, max_passes=2, heartbeat=hb)
    assert hb.beats == [(False, "latest slot failed")] * 2


def test_ingest_watch_reports_connection(seeded_db):
    from services import ingest

    states = iter([True, False])
    client = SimpleNamespace(is_connected=lambda: next(states), _thread=None)
    hb = Recorder()
    ingest.watch(client, hb, pause=lambda s: None, max_passes=2)
    assert hb.beats == [(True, "connected"), (False, "broker unreachable")]


def test_ingest_watch_stops_when_network_thread_dies():
    from services import ingest

    client = SimpleNamespace(is_connected=lambda: True, _thread=SimpleNamespace(is_alive=lambda: False))
    hb = Recorder()
    ingest.watch(client, hb, pause=lambda s: None, max_passes=5)
    assert hb.beats == []  # no beat: the systemd watchdog will restart the service


# --- device health ------------------------------------------------------------------

def test_telemetry_updates_device_health(seeded_db):
    from services import ingest

    body = {"device_id": 1, "ts_utc": None, "temperature_c": 20.0, "humidity_pct": 40.0,
            "light_raw": 100, "relays": [0] * 8, "uptime_s": 3600, "mem_free": 140000, "rssi_dbm": -63}
    ingest.handle_message("greenhouse/1/telemetry", json.dumps(body).encode(), "2026-09-26 19:00:00")
    status = db.device_status()
    assert (status["status"], status["last_seen_utc"], status["uptime_s"], status["mem_free"], status["rssi_dbm"]) == \
        ("online", "2026-09-26 19:00:00", 3600, 140000, -63)


def test_telemetry_keeps_online_since_time(seeded_db):
    db.set_device_status("online", "2026-09-26 18:00:00")
    db.update_device_health(1, "2026-09-26 19:00:00", uptime_s=10)
    status = db.device_status()
    assert status["updated_utc"] == "2026-09-26 18:00:00"  # online since, unchanged
    db.set_device_status("offline", "2026-09-26 19:05:00")
    db.update_device_health(1, "2026-09-26 19:10:00")
    assert db.device_status()["updated_utc"] == "2026-09-26 19:10:00"  # back online now


def test_home_shows_service_and_device_health(seeded_db):
    db.update_device_health(1, utc_timestamp(), uptime_s=90000, mem_free=143360, rssi_dbm=-58)
    db.record_heartbeat("ingest", True, "connected")
    db.record_heartbeat("automation", False, "db locked")
    at = AppTest.from_file(str(SERVER_DIR / "views/home.py"), default_timeout=30).run()
    assert not at.exception
    text = [m.value for m in at.markdown]
    assert any(t.startswith("Last message just now · up 1 d 1 h") for t in text)
    assert "Wi-Fi good (-58 dBm) · 140 KB free" in text
    assert ":green-badge[:material/check_circle: OK]" in text
    assert ":orange-badge[:material/warning: Degraded]" in text
    assert ":gray-badge[:material/help: Unknown]" in text  # weather never beat
    assert any("connected" in t for t in text)
