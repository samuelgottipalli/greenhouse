"""Tests for picoside/setup_config.py (runs on a computer, not the Pico)."""
import importlib
import json
import sys

import pytest

from support import PICO_TOOLS_DIR


@pytest.fixture
def setup_config(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(PICO_TOOLS_DIR))
    sys.modules.pop("setup_config", None)
    module = importlib.import_module("setup_config")
    monkeypatch.setattr(module, "CONFIG_FILE", tmp_path / "config.json")
    yield module
    sys.modules.pop("setup_config", None)
    sys.modules.pop("clock", None)


@pytest.mark.parametrize(
    "zone, offset, rule",
    [
        ("America/Los_Angeles", -480, "us"),
        ("America/Chicago", -360, "us"),
        ("Europe/London", 0, "eu"),
        ("Europe/Berlin", 60, "eu"),
        ("Asia/Kolkata", 330, "none"),
        ("America/Phoenix", -420, "none"),
        ("UTC", 0, "none"),
    ],
)
def test_timezone_settings(setup_config, zone, offset, rule):
    settings, warning = setup_config.timezone_settings(zone, year=2026)
    assert settings == {"timezone": zone, "utc_offset_minutes": offset, "dst_rule": rule}
    assert warning is None


def test_unsupported_dst_rule_warns(setup_config):
    settings, warning = setup_config.timezone_settings("Australia/Sydney", year=2026)
    assert settings["utc_offset_minutes"] == 600 and settings["dst_rule"] == "none"
    assert "daylight-saving rule" in warning


def test_build_config_merges_and_blanks_optional_login(setup_config):
    base = json.loads(setup_config.EXAMPLE_FILE.read_text())
    config, warning = setup_config.build_config(
        base, {"wifi_ssid": "net", "mqtt_user": "", "mqtt_password": "", "timezone": "Europe/London"}
    )
    assert config["wifi_ssid"] == "net"
    assert config["mqtt_user"] is None and config["mqtt_password"] is None
    assert (config["utc_offset_minutes"], config["dst_rule"]) == (0, "eu")
    assert config["relay_pins"] == base["relay_pins"]


def test_main_writes_config(setup_config, monkeypatch):
    answers = iter(["mynet", "broker.local", "", "", "2", "Nowhere/Invalid", "America/New_York"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(setup_config.getpass, "getpass", lambda prompt: "")
    monkeypatch.setattr(setup_config, "load_base",
                        lambda: json.loads(setup_config.EXAMPLE_FILE.read_text()))
    assert setup_config.main() == 0
    written = json.loads(setup_config.CONFIG_FILE.read_text())
    assert written["wifi_ssid"] == "mynet" and written["device_id"] == 2
    assert (written["timezone"], written["utc_offset_minutes"], written["dst_rule"]) == ("America/New_York", -300, "us")
