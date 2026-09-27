"""Tests with two controllers (PLAN 4.4)."""
import re

import pytest
from streamlit.testing.v1 import AppTest

from core import db
from scripts import add_device
from support import REPO_ROOT, SERVER_DIR


@pytest.fixture
def two_devices(seeded_db, db_conn):
    add_device.add_device(2, "picow2", path=seeded_db)
    db_conn.executemany(
        "INSERT INTO relay_events (device_id, relay_id, event_utc, state, source) VALUES (?, ?, ?, ?, ?)",
        [(2, r, "2025-10-27 01:00:00", 1 if r == 3 else 0, "web") for r in (1, 2, 3, 4)],
    )
    db_conn.commit()
    return seeded_db


def run_page(page, device_id=None):
    at = AppTest.from_file(str(SERVER_DIR / page), default_timeout=30)
    if device_id:
        at.session_state["device_id"] = device_id
    return at.run()


def test_add_device_seeds_relays_and_settings(two_devices):
    assert db.list_devices() == {1: "picow1", 2: "picow2"}
    assert db.relay_names(device_id=2)[3] == "heater"
    assert len(db.read_thresholds(device_id=2)) == 4
    assert len(db.read_watering_schedule(device_id=2, profile="default")) == 4


@pytest.mark.parametrize("args", [(2, "other"), (3, "picow1"), (0, "zero"), (4, " ")])
def test_add_device_rejects_duplicates_and_bad_input(two_devices, args):
    with pytest.raises(ValueError):
        add_device.add_device(*args, path=two_devices)


def test_add_device_script_prints_acl(seeded_db, capsys):
    assert add_device.main(["5", "north-house"]) == 0
    out = capsys.readouterr().out
    assert "user greenhouse-device-5" in out and "topic read greenhouse/5/settings" in out
    assert add_device.main(["5", "north-house"]) == 1


def test_selector_hidden_with_one_device(seeded_db):
    assert not run_page("views/home.py").sidebar.selectbox


def test_selector_switches_pages_to_another_device(two_devices):
    at = run_page("views/control.py")
    assert at.sidebar.selectbox[0].options == ["picow1 (#1)", "picow2 (#2)"]
    assert at.toggle(key="3").value is False  # device 1 heater off
    at.sidebar.selectbox[0].set_value(2).run()
    assert at.toggle(key="3").value is True   # device 2 heater on
    assert at.toggle(key="2").value is False


def test_control_commands_go_to_selected_device(two_devices, monkeypatch):
    import core.mqtt

    sent = []
    monkeypatch.setattr(core.mqtt, "publish_relay_command", lambda **kw: sent.append(kw) or True)
    at = run_page("views/control.py", device_id=2)
    at.toggle(key="1").set_value(True).run()
    assert sent == [{"relay_id": 1, "state": 1, "source": "web", "device_id": 2}]
    assert db.latest_relay_states(device_id=2).set_index("relay_id").loc[1, "state"] == 1
    assert db.latest_relay_states(device_id=1).set_index("relay_id").loc[1, "state"] == 0


def test_settings_saved_for_selected_device_only(two_devices):
    at = run_page("views/greenhouse_settings.py", device_id=2)
    at.number_input(key="fan_on_humidity").set_value(77.0)
    next(b for b in at.button if b.label == "Save").click().run()
    limits = lambda d: db.read_thresholds(device_id=d).set_index("name").loc["fan_on_humidity_pct", "value"]
    assert (limits(1), limits(2)) == (50.0, 77.0)


def test_automation_runs_every_device(two_devices, db_conn, monkeypatch):
    from services import automation

    db_conn.executemany("INSERT INTO sensor_readings VALUES (?, 1, ?, 5.0)",
                        [(1, "2030-01-01 00:00:00"), (2, "2030-01-01 00:00:00")])
    db_conn.commit()
    sent = []
    monkeypatch.setattr(automation, "publish_relay_command", lambda **kw: sent.append(kw) or True)
    monkeypatch.setattr(automation, "publish_device_settings", lambda payload, device_id: True)
    from datetime import datetime, timezone

    real_run_once = automation.run_once
    monkeypatch.setattr(automation, "run_once",
                        lambda device_id: real_run_once(now=datetime(2030, 1, 1, 0, 1, tzinfo=timezone.utc),
                                                        device_id=device_id))
    automation.main(pause=lambda s: None, max_passes=1)
    heater = {(c["device_id"], c["state"]) for c in sent if c["relay_id"] == 3}
    assert (1, 1) in heater  # device 1: cold, heater was off -> on
    assert not any(c["device_id"] == 2 and c["relay_id"] == 3 for c in sent)  # device 2 heater already on


def test_no_relay_or_device_ids_hard_coded_outside_seed_data():
    offenders = []
    for path in (REPO_ROOT / "server").rglob("*.py"):
        if path.name in ("migrations.py",) or "scripts" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(relay_id|device_id)\s*=\s*\d", line) or re.search(r"'00\d'", line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == []
