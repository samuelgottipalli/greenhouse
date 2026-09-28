"""
Tests for the server side of over-the-air updates: the manifest
(core/firmware.py), the file service (services/firmware_server.py), storing
the controller's reports (ingest, db) and the Controllers and Home pages.
"""
import json
import threading
import urllib.error
import urllib.request

import pytest
from streamlit.testing.v1 import AppTest

from core import db, firmware, settings, setup_code
from services import firmware_server, ingest
from support import SERVER_DIR, run_section, section_app


@pytest.fixture
def code_dir(tmp_path):
    root = tmp_path / "device"
    (root / "lib" / "__pycache__").mkdir(parents=True)
    (root / "controller.py").write_bytes(b"A = 1\n")
    (root / "lib" / "x.py").write_bytes(b"X = 1\n")
    (root / "lib" / "__pycache__" / "x.cpython-311.pyc").write_bytes(b"\0")
    (root / "main.py").write_bytes(b"loader\n")
    (root / "boot.py").write_bytes(b"guard\n")
    (root / "config.json").write_text('{"wifi_password": "secret"}')
    return root


def test_manifest_lists_updatable_files(code_dir):
    manifest = firmware.manifest(code_dir, url="http://h:8081/")
    assert [f["path"] for f in manifest["files"]] == ["controller.py", "lib/x.py"]
    entry = manifest["files"][0]
    assert entry["size"] == 6 and len(entry["sha256"]) == 64
    assert manifest["url"] == "http://h:8081/" and len(manifest["version"]) == 12


def test_version_changes_with_any_file(code_dir):
    before = firmware.available_version(code_dir)
    assert firmware.available_version(code_dir) == before
    (code_dir / "lib" / "x.py").write_bytes(b"X = 2\n")
    assert firmware.available_version(code_dir) != before
    (code_dir / "lib" / "x.py").write_bytes(b"X = 1\n")
    assert firmware.available_version(code_dir) == before


def test_line_endings_do_not_change_the_version(code_dir):
    before = firmware.manifest(code_dir, url="")
    (code_dir / "controller.py").write_bytes(b"A = 1\r\n")
    assert firmware.manifest(code_dir, url="") == before


def test_firmware_url(monkeypatch):
    monkeypatch.setattr(setup_code, "server_address", lambda: "192.168.1.20")
    monkeypatch.setattr(settings, "FIRMWARE_PORT", 8099)
    assert firmware.firmware_url() == "http://192.168.1.20:8099/"


def test_publish_update(monkeypatch, code_dir):
    sent = []
    monkeypatch.setattr(firmware, "single", lambda **kw: sent.append(kw))
    update = firmware.manifest(code_dir, url="http://h/")
    assert firmware.publish_update(3, update) is True
    (message,) = sent
    assert message["topic"] == "greenhouse/3/firmware/update"
    assert message["qos"] == 1 and not message.get("retain")
    assert json.loads(message["payload"]) == update


def test_publish_update_broker_down(monkeypatch, code_dir):
    def refuse(**kw):
        raise ConnectionRefusedError(111, "refused")

    monkeypatch.setattr(firmware, "single", refuse)
    assert firmware.publish_update(1, firmware.manifest(code_dir, url="http://h/")) is False


# --- the HTTP service ----------------------------------------------------------


@pytest.fixture
def base_url(code_dir):
    server = firmware_server.make_server(port=0, host="127.0.0.1", device_dir=code_dir)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()


def fetch(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, b""


def test_serves_manifest_and_listed_files(base_url, code_dir):
    status, body = fetch(base_url + "manifest.json")
    assert status == 200 and json.loads(body)["files"][1]["path"] == "lib/x.py"
    assert fetch(base_url + "files/lib/x.py") == (200, b"X = 1\n")


@pytest.mark.parametrize("path", [
    "files/config.json", "files/main.py", "files/boot.py", "files/../device/config.json",
    "files/lib/__pycache__/x.cpython-311.pyc", "config.json", "", "files/",
])
def test_serves_nothing_else(base_url, path):
    assert fetch(base_url + path)[0] == 404


def test_new_files_are_offered_at_once(base_url, code_dir):
    (code_dir / "new.py").write_bytes(b"N = 1\n")
    assert fetch(base_url + "files/new.py") == (200, b"N = 1\n")


# --- reports from the controller ------------------------------------------------


def report(**fields):
    body = {"device_id": 1, "version": "3f9a0c1b2d4e", "state": "updated", "detail": "Updated from x",
            "ts_utc": "2026-09-27 10:00:00"}
    body.update(fields)
    return json.dumps(body).encode()


def test_ingest_stores_firmware_report(seeded_db):
    result = ingest.handle_message("greenhouse/1/firmware", report(), "2026-09-27 10:00:05")
    assert result == "firmware of 1: 3f9a0c1b2d4e updated"
    status = db.device_status(1)
    assert (status["firmware_version"], status["firmware_state"], status["firmware_detail"],
            status["firmware_utc"]) == ("3f9a0c1b2d4e", "updated", "Updated from x", "2026-09-27 10:00:05")


def test_firmware_report_keeps_other_status(seeded_db):
    db.set_device_status("offline", "2026-09-27 09:00:00", device_id=1)
    ingest.handle_message("greenhouse/1/firmware", report(state="running"), "2026-09-27 10:00:05")
    status = db.device_status(1)
    assert status["status"] == "offline" and status["firmware_state"] == "running"


@pytest.mark.parametrize("body", [
    report(state="exploded"), report(version=""), report(version=7), b"[]", b"not json",
])
def test_ingest_ignores_bad_firmware_reports(seeded_db, body):
    assert "ignored" in ingest.handle_message("greenhouse/1/firmware", body, "2026-09-27 10:00:05")
    assert db.device_status(1) is None


# --- pages -------------------------------------------------------------------------


@pytest.fixture
def controllers_page(seeded_db, monkeypatch, tmp_path):
    from core import device_credentials

    monkeypatch.setattr(device_credentials, "CREDENTIALS_FILE", tmp_path / "creds.json")
    monkeypatch.setattr(setup_code, "lan_address", lambda: "192.168.1.20")

    def run():
        return run_section("controllers")

    return run


def update_button(at):
    return next(b for b in at.button if b.label == "Update controller")


def test_page_up_to_date(controllers_page):
    ingest.handle_message("greenhouse/1/firmware", report(version=firmware.available_version()), "2026-09-27 10:00:05")
    at = controllers_page()
    assert not at.exception
    assert "Up to date" in at.success[0].value
    assert not [b for b in at.button if b.label == "Update controller"]


def test_page_offers_update_when_online(controllers_page, monkeypatch):
    sent = []
    monkeypatch.setattr(firmware, "single", lambda **kw: sent.append(kw))
    db.set_device_status("online", "2026-09-27 09:00:00", device_id=1)
    ingest.handle_message("greenhouse/1/firmware", report(version="old000000000", state="rolled_back",
                                                          detail="Version x did not start"), "2026-09-27 10:00:05")
    at = controllers_page()
    assert "didn't start properly" in at.caption[0].value
    button = update_button(at)
    assert not button.disabled
    button.click().run()
    assert not at.exception
    (message,) = sent
    update = json.loads(message["payload"])
    assert update["url"] == f"http://192.168.1.20:{settings.FIRMWARE_PORT}/"
    assert update["version"] == firmware.available_version()
    assert "Update sent" in at.success[0].value


def test_page_disables_update_while_offline(controllers_page):
    db.set_device_status("offline", "2026-09-27 09:00:00", device_id=1)
    at = controllers_page()
    assert update_button(at).disabled
    assert any("must be online" in c.value for c in at.caption)


def test_home_links_to_available_update(seeded_db):
    db.update_device_health(1, "2026-09-27 10:00:00", uptime_s=60)
    ingest.handle_message("greenhouse/1/firmware", report(version="old000000000", state="running"), "2026-09-27 10:00:05")
    at = AppTest.from_file(str(SERVER_DIR / "views/home.py"), default_timeout=30).run()
    assert not at.exception
    assert any("Software update available" in m.value for m in at.markdown)


# --- version names (Phase 6) -------------------------------------------------


def test_available_name_reads_the_version_file(tmp_path):
    assert firmware.available_name(tmp_path) == "1.0.0"  # no version.py: older than names
    (tmp_path / "version.py").write_text('"""Doc."""\n\nVERSION = "2.3.4-dev"\n', encoding="utf-8")
    assert firmware.available_name(tmp_path) == "2.3.4-dev"
    assert firmware.manifest(tmp_path, url="")["name"] == "2.3.4-dev"


def test_this_checkout_offers_its_own_version():
    from version import VERSION

    assert firmware.available_name() == firmware.manifest(url="")["name"]
    assert firmware.available_name()  # picoside/device/version.py is there
    assert VERSION  # server/version.py


@pytest.mark.parametrize("status, expected", [
    ({}, None),                                                              # never reported
    ({"firmware_version": "aaaaaaaaaaaa"}, True),                            # 1.0.0 controller, other build
    ({"firmware_version": "bbbbbbbbbbbb", "firmware_name": "1.0.0"}, False),  # same build
    ({"firmware_version": "unknown", "firmware_name": "1.1.0"}, False),      # set up by hand: same name
    ({"firmware_version": "unknown", "firmware_name": "1.0.9"}, True),       # set up by hand: other name
    ({"firmware_version": "unknown"}, True),                                  # 1.0.0 set up by hand
])
def test_update_available(status, expected):
    assert firmware.update_available(status, "bbbbbbbbbbbb", "1.1.0") is expected


def test_installed_name():
    assert firmware.installed_name({}) is None
    assert firmware.installed_name({"firmware_version": "abc"}) == "1.0.0"
    assert firmware.installed_name({"firmware_version": "abc", "firmware_name": "1.1.0"}) == "1.1.0"


def test_ingest_stores_the_version_name(seeded_db):
    ingest.handle_message("greenhouse/1/firmware", report(version="3f9a0c1b2d4e", name="1.1.0"),
                          "2026-09-27 10:00:05")
    status = db.device_status(1)
    assert (status["firmware_version"], status["firmware_name"]) == ("3f9a0c1b2d4e", "1.1.0")
    ingest.handle_message("greenhouse/1/firmware", report(version="3f9a0c1b2d4e"), "2026-09-27 10:00:06")
    assert db.device_status(1)["firmware_name"] is None  # a 1.0.0 report has no name


def test_page_shows_version_names(controllers_page):
    ingest.handle_message("greenhouse/1/firmware", report(version="aaaaaaaaaaaa"), "2026-09-27 10:00:05")
    at = controllers_page()
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Installed": "1.0.0", "Available": firmware.available_name()}
    assert any("Builds: installed `aaaaaaaaaaaa`" in c.value for c in at.caption)
