"""
Keep docs/RUNBOOK.md honest: files, scripts, LCD messages and config keys it
mentions must exist in the code. Also tests scripts/telemetry_report.py.
"""
import re
from datetime import datetime, timedelta, timezone

import pytest

from support import PICO_DIR, REPO_ROOT, SERVER_DIR

RUNBOOK = (REPO_ROOT / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
DEVICE_CODE = "\n".join(p.read_text(encoding="utf-8") for p in PICO_DIR.glob("*.py"))


def test_repo_paths_exist():
    paths = set(re.findall(r"(?:deploy|picoside|server|docs)/[\w./-]+\.(?:py|conf|acl|md|json|sql)", RUNBOOK))
    assert paths
    missing = [p for p in paths if not (REPO_ROOT / p).exists() and not p.endswith("config.json")]
    assert missing == []


def test_python_modules_exist():
    for module in set(re.findall(r"-m ((?:scripts|services)\.\w+)", RUNBOOK)):
        assert (SERVER_DIR / (module.replace(".", "/") + ".py")).exists(), module


@pytest.mark.parametrize(
    "message",
    ["Connecting to WiFi...", "WiFi connected. Syncing clock...", "Connecting to MQTT...",
     "WiFi unavailable, will retry.", "Clock not set", "IP address:", "NoMQTT", "NoWiFi",
     "No Wi-Fi SSID set", "No MQTT broker set", "MQTT connect failed", "LOCAL"],
)
def test_lcd_and_console_messages_exist(message):
    assert message in RUNBOOK
    assert message in DEVICE_CODE


@pytest.mark.parametrize("key", ["watchdog", "relay_active_low"])
def test_config_keys_exist(key):
    import json

    assert f'"{key}"' in RUNBOOK
    assert key in json.loads((PICO_DIR / "config.example.json").read_text())


def test_accounts_match_acl():
    acl = (REPO_ROOT / "deploy" / "mosquitto" / "greenhouse.acl").read_text()
    for account in ("greenhouse-server", "greenhouse-device-1"):
        assert f"user {account}" in acl and account in RUNBOOK


def test_telemetry_report(seeded_db, db_conn, capsys):
    from scripts import telemetry_report

    now = datetime(2030, 1, 2, tzinfo=timezone.utc)
    rows = [(1, 1, (now - timedelta(minutes=5 * i)).strftime("%Y-%m-%d %H:%M:%S"), 20.0) for i in range(12)]
    db_conn.executemany("INSERT INTO sensor_readings VALUES (?, ?, ?, ?)", rows)
    db_conn.commit()
    assert telemetry_report.coverage(1, 300, 1, now=now) == (12, 12)
    assert telemetry_report.coverage(2, 300, 1, now=now) == (12, 24)
    db_conn.execute("DELETE FROM sensor_readings")
    db_conn.commit()
    assert telemetry_report.main(["--hours", "1"]) == 1  # nothing stored: below 99 %
    assert "0 of 12 expected readings" in capsys.readouterr().out
