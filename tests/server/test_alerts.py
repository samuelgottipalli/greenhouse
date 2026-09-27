"""Tests for alerts (PLAN 4.6): conditions, cooldown, resolution and delivery."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from core import alerts, db, notify, settings
from core.timeutil import utc_timestamp

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=timezone.utc)


class Outbox:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def __call__(self, title, message, urgent=False):
        self.sent.append((title, message, urgent))
        return self.ok


def reading(db_conn, temp, at=NOW - timedelta(minutes=2)):
    db_conn.execute("INSERT OR REPLACE INTO sensor_readings VALUES (1, 1, ?, ?)", (utc_timestamp(at), temp))
    db_conn.commit()


def all_services_ok(at=NOW):
    for service in ("ingest", "automation", "weather"):
        db.record_heartbeat(service, True, "", updated_utc=utc_timestamp(at))


@pytest.fixture
def healthy(seeded_db, db_conn):
    all_services_ok()
    reading(db_conn, 20.0)
    return db_conn


# --- conditions -------------------------------------------------------------------------

def test_no_conditions_when_healthy(healthy):
    assert alerts.current_conditions(NOW) == {}


@pytest.mark.parametrize("temp, key", [(2.0, "temp_low:1"), (45.0, "temp_high:1")])
def test_temperature_out_of_range(healthy, temp, key):
    reading(healthy, temp, at=NOW - timedelta(minutes=1))
    conditions = alerts.current_conditions(NOW)
    assert list(conditions) == [key] and conditions[key][1] is True


def test_stale_readings(healthy):
    later = NOW + timedelta(minutes=30)
    all_services_ok(later)
    assert list(alerts.current_conditions(later)) == ["stale:1"]


def test_offline_replaces_stale_and_temperature(healthy):
    db.set_device_status("offline", utc_timestamp(NOW))
    reading(healthy, 2.0, at=NOW - timedelta(minutes=1))
    assert list(alerts.current_conditions(NOW)) == ["offline:1"]


def test_service_down_and_degraded(healthy):
    db.record_heartbeat("ingest", False, "broker unreachable", updated_utc=utc_timestamp(NOW))
    db.record_heartbeat("weather", True, "", updated_utc=utc_timestamp(NOW - timedelta(minutes=10)))
    conditions = alerts.current_conditions(NOW)
    assert set(conditions) == {"service_degraded:ingest", "service_down:weather"}
    assert "broker unreachable" in conditions["service_degraded:ingest"][0]


def test_device_that_never_reported_is_not_an_alert(seeded_db, db_conn):
    all_services_ok()
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.commit()
    assert alerts.current_conditions(NOW) == {}


# --- cooldown and resolution --------------------------------------------------------------

def run(now, outbox):
    all_services_ok(now)
    return alerts.process(now=now, send=outbox)


def test_each_alert_once_per_cooldown_window(healthy, monkeypatch):
    monkeypatch.setattr(settings, "ALERT_COOLDOWN_MIN", 60)
    outbox = Outbox()
    reading(healthy, 45.0, at=NOW - timedelta(minutes=1))
    assert run(NOW, outbox)["raised"] == 1
    for minutes in range(2, 60, 2):  # checks every 2 min inside the cooldown
        t = NOW + timedelta(minutes=minutes)
        reading(healthy, 45.0, at=t - timedelta(minutes=1))
        run(t, outbox)
    assert len(outbox.sent) == 1
    t = NOW + timedelta(minutes=60)
    reading(healthy, 45.0, at=t - timedelta(minutes=1))
    assert run(t, outbox)["repeated"] == 1
    assert outbox.sent[-1][0] == "Still a problem"


def test_resolved_once(healthy):
    outbox = Outbox()
    reading(healthy, 45.0, at=NOW - timedelta(minutes=1))
    run(NOW, outbox)
    t = NOW + timedelta(minutes=2)
    reading(healthy, 25.0, at=t - timedelta(minutes=1))
    assert run(t, outbox)["resolved"] == 1
    assert run(t + timedelta(minutes=2), outbox) == {"raised": 0, "repeated": 0, "resolved": 0}
    assert [m[0] for m in outbox.sent] == ["Alert", "Resolved"]
    assert db.active_alerts() == []


def test_recurrence_after_resolution_is_a_new_alert(healthy):
    outbox = Outbox()
    for minutes, temp in ((0, 45.0), (2, 25.0), (4, 45.0)):
        t = NOW + timedelta(minutes=minutes)
        reading(healthy, temp, at=t - timedelta(seconds=30))
        run(t, outbox)
    assert [m[0] for m in outbox.sent] == ["Alert", "Resolved", "Alert"]


def test_failed_delivery_is_retried_next_run(healthy):
    reading(healthy, 45.0, at=NOW - timedelta(minutes=1))
    run(NOW, Outbox(ok=False))
    working = Outbox()
    t = NOW + timedelta(minutes=2)
    reading(healthy, 45.0, at=t - timedelta(minutes=1))
    assert run(t, working)["repeated"] == 1  # never delivered, so sent at the next check
    assert db.active_alerts()[0]["alert_key"] == "temp_high:1"


# --- delivery -------------------------------------------------------------------------------

def test_log_only_when_no_channel(caplog):
    assert notify.configured_channels() == []
    assert notify.deliver("Alert", "hello") is True
    assert "ALERT Alert: hello" in caplog.text


def test_ntfy(monkeypatch):
    calls = []

    def fake_post(url, data, headers, timeout):
        calls.append((url, data, headers))
        return SimpleNamespace(raise_for_status=lambda: None)

    monkeypatch.setattr(settings, "NTFY_URL", "https://ntfy.example/greenhouse")
    monkeypatch.setattr(settings, "NTFY_TOKEN", "tk")
    monkeypatch.setattr(notify, "post", fake_post)
    assert notify.deliver("Alert", "too hot", urgent=True) is True
    url, data, headers = calls[0]
    assert (url, data) == ("https://ntfy.example/greenhouse", b"too hot")
    assert headers["Priority"] == "high" and headers["Authorization"] == "Bearer tk"


def test_email(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.calls = [("connect", host, port)]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            self.calls.append("starttls")

        def login(self, user, password):
            self.calls.append(("login", user))

        def send_message(self, message):
            sent.append((self.calls, message["To"], message["Subject"], message.get_content().strip()))

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example")
    monkeypatch.setattr(settings, "SMTP_USER", "me@example.com")
    monkeypatch.setattr(settings, "ALERT_EMAIL_TO", "me@example.com")
    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    assert notify.deliver("Alert", "too cold") is True
    calls, to, subject, body = sent[0]
    assert calls == [("connect", "smtp.example", 587), "starttls", ("login", "me@example.com")]
    assert (to, subject, body) == ("me@example.com", "[Greenhouse] Alert", "too cold")


def test_all_channels_failing(monkeypatch):
    monkeypatch.setattr(settings, "NTFY_URL", "https://ntfy.example/x")

    def boom(*a, **k):
        raise ConnectionError("offline")

    monkeypatch.setattr(notify, "post", boom)
    assert notify.deliver("Alert", "x") is False


# --- service and page ---------------------------------------------------------------------

def test_alerts_service_runs(healthy):
    from services import alerts as alerts_service

    assert alerts_service.main() == 0  # no channel configured in tests: log only


def test_home_shows_active_alerts(seeded_db):
    from streamlit.testing.v1 import AppTest
    from support import SERVER_DIR

    db.save_alert("temp_high:1", True, "picow1: greenhouse is 45.0 °C, above 40 °C.", utc_timestamp(), None)
    db.save_alert("stale:1", False, "old and resolved", utc_timestamp(), None)
    at = AppTest.from_file(str(SERVER_DIR / "views/home.py"), default_timeout=30).run()
    assert len(at.error) == 1 and "above 40 °C" in at.error[0].value
