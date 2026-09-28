"""
Tests for setup codes (server/core/setup_code.py), stored controller logins
(core/device_credentials.py) and the Controllers page.

The round-trip test decodes server-made codes with the controller's own
code (picoside/device/provision.py), so both sides stay in step.
"""
import importlib
import json
import os
import sys

import pytest
from streamlit.testing.v1 import AppTest

from support import PICO_DIR, SERVER_DIR, run_section, section_app


@pytest.fixture
def provision(monkeypatch):
    """The controller's provision module, imported on CPython."""
    monkeypatch.syspath_prepend(str(PICO_DIR))
    for name in ("provision", "zones"):
        sys.modules.pop(name, None)
    yield importlib.import_module("provision")
    for name in ("provision", "zones"):
        sys.modules.pop(name, None)


@pytest.mark.parametrize("user, password, zone", [
    ("greenhouse-device-3", "p@ss w/ord+=", "America/Chicago"),
    (None, None, None),
    ("greenhouse-device-3", "", "UTC"),
])
def test_code_round_trip(provision, user, password, zone):
    from core import setup_code

    code = setup_code.encode("192.168.1.20", 1884, 3, user, password, zone)
    assert code.startswith("GH1-") and "=" not in code
    values = provision.decode_setup_code(code)
    assert values["mqtt_broker"] == "192.168.1.20" and values["mqtt_port"] == 1884
    assert values["device_id"] == 3
    assert values["mqtt_user"] == user
    assert values["mqtt_password"] == (password or None)
    assert values.get("timezone") == zone


def test_code_via_setup_form(provision, monkeypatch):
    """A code from the server, pasted into the controller's form, gives a working config."""
    from core import setup_code

    monkeypatch.syspath_prepend(str(PICO_DIR))
    sys.modules.pop("config", None)
    config = importlib.import_module("config").load_config("no_such_file.json")
    sys.modules.pop("config", None)
    code = setup_code.encode("10.0.0.2", 1883, 1, "greenhouse-device-1", "pw123", "Europe/London")
    changes, errors = provision.form_to_settings(
        {"ssid": "home", "password": "wifi-password", "code": code, "tz": ""}, config)
    assert errors == []
    assert changes["mqtt_client_id"] == "greenhouse-device-1" and changes["dst_rule"] == "eu"


def test_setup_link_and_qr():
    from core import setup_code

    link = setup_code.setup_link("GH1-abc")
    assert link == "http://192.168.4.1/?code=GH1-abc"
    png = setup_code.qr_png(link)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width = int.from_bytes(png[16:20], "big")
    assert width >= 200  # big enough to scan from a screen


def test_server_address(monkeypatch):
    from core import settings, setup_code

    monkeypatch.setattr(settings, "PUBLIC_HOST", "192.168.1.5")
    assert setup_code.server_address() == "192.168.1.5"
    monkeypatch.setattr(settings, "PUBLIC_HOST", "")
    monkeypatch.setattr(settings, "MQTT_HOST", "broker.lan")
    assert setup_code.server_address() == "broker.lan"
    monkeypatch.setattr(settings, "MQTT_HOST", "localhost")
    monkeypatch.setattr(setup_code, "lan_address", lambda: "10.1.2.3")
    assert setup_code.server_address() == "10.1.2.3"


def test_lan_address_is_a_real_address_or_none():
    from core import setup_code

    address = setup_code.lan_address()
    assert address is None or (not address.startswith("127.") and address.count(".") == 3)


def test_credentials_store(tmp_path):
    from core import device_credentials as creds

    path = tmp_path / "data" / "device_credentials.json"
    assert creds.get(1, path) is None
    creds.save(1, "greenhouse-device-1", "one", path)
    creds.save(2, "greenhouse-device-2", "two", path)
    creds.save(1, "greenhouse-device-1", "uno", path)
    assert creds.get(1, path) == {"user": "greenhouse-device-1", "password": "uno"}
    assert set(creds.load(path)) == {1, 2}
    assert not path.with_suffix(".tmp").exists()
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_credentials_store_ignores_damaged_file(tmp_path):
    from core import device_credentials as creds

    path = tmp_path / "creds.json"
    path.write_text("not json")
    assert creds.load(path) == {}
    path.write_text(json.dumps([1, 2]))
    assert creds.load(path) == {}


def test_new_password_and_user():
    from core import device_credentials as creds

    first, second = creds.new_password(), creds.new_password()
    assert first != second and len(first) == 20
    assert creds.device_user(4) == "greenhouse-device-4"


# --- the Controllers page ----------------------------------------------------


@pytest.fixture
def page(seeded_db, monkeypatch, tmp_path):
    from core import device_credentials, settings, setup_code

    monkeypatch.setattr(device_credentials, "CREDENTIALS_FILE", tmp_path / "creds.json")
    monkeypatch.setattr(setup_code, "lan_address", lambda: "192.168.1.20")
    monkeypatch.setattr(settings, "MQTT_USERNAME", "greenhouse-server")

    def run():
        return run_section("controllers")

    return run


def test_page_shows_code_for_stored_login(page, provision, tmp_path):
    from core import device_credentials

    device_credentials.save(1, "greenhouse-device-1", "secret-pw")
    at = page()
    assert not at.exception
    (code,) = [c.value for c in at.code]
    values = provision.decode_setup_code(code)
    assert values["mqtt_broker"] == "192.168.1.20" and values["mqtt_password"] == "secret-pw"


def test_page_asks_for_missing_password(page):
    at = page()
    assert not at.exception
    assert not at.code
    at.text_input[0].input("typed-pw")
    next(b for b in at.button if b.label == "Save password").click().run()
    assert not at.exception
    from core import device_credentials

    assert device_credentials.get(1) == {"user": "greenhouse-device-1", "password": "typed-pw"}
    assert at.code  # the code shows once the password is known


def test_page_without_broker_logins(page, monkeypatch):
    from core import settings

    monkeypatch.setattr(settings, "MQTT_USERNAME", None)
    at = page()
    assert not at.exception and at.code


def test_page_without_network_address(page, monkeypatch):
    from core import setup_code

    monkeypatch.setattr(setup_code, "lan_address", lambda: None)
    at = page()
    assert not at.exception and not at.code
    assert "PUBLIC_HOST" in at.warning[0].value
