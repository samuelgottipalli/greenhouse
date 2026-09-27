"""
Tests for over-the-air updates: the controller side (picoside/device/ota.py,
boot.py and the controller's update handling) against the real server side
(server/core/firmware.py and services/firmware_server.py) over real HTTP.

The device code runs in the test's temporary folder (the fake Pico's flash).
"""
import hashlib
import importlib
import json
import sys
import threading

import pytest

from pico_fakes import FakeLcd, FakeWLAN
from test_controller import FakeButtons, FakeClock, FakeSensors
from test_net import FakeClient

from core import firmware
from services import firmware_server
from support import PICO_DIR


@pytest.fixture
def serve():
    """Run the real firmware server on a free local port for a folder."""
    servers = []

    def _serve(device_dir):
        server = firmware_server.make_server(port=0, host="127.0.0.1", device_dir=device_dir)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return "http://127.0.0.1:{}/".format(server.server_address[1])

    yield _serve
    for server in servers:
        server.shutdown()
        server.server_close()


@pytest.fixture
def source(tmp_path):
    """A small 'new version' of the controller code on the server."""
    root = tmp_path / "srv"
    (root / "lib").mkdir(parents=True)
    (root / "controller.py").write_bytes(b"VERSION = 2\n")
    (root / "net.py").write_bytes(b"NET = 2\n")
    (root / "lib" / "extra.py").write_bytes(b"EXTRA = 1\n")
    (root / "main.py").write_bytes(b"never sent\n")
    (root / "boot.py").write_bytes(b"never sent\n")
    return root


@pytest.fixture
def installed(pico, tmp_path):
    """The 'old version' on the controller's flash (the current folder)."""
    (tmp_path / "controller.py").write_bytes(b"VERSION = 1\n")
    (tmp_path / "net.py").write_bytes(b"NET = 2\n")  # already the same as the new one
    pico.ota.mark_current("old-version")
    return tmp_path


def update_for(source, url):
    return firmware.manifest(source, url=url)


# --- checks ----------------------------------------------------------------


@pytest.mark.parametrize("path, ok", [
    ("controller.py", True),
    ("lib/umqtt/simple.py", True),
    ("main.py", False),
    ("boot.py", False),
    ("config.json", False),
    ("../evil.py", False),
    ("/abs.py", False),
    ("lib//x.py", False),
    ("ota_old/x.py", False),
    ("notes.txt", False),
    ("sp ace.py", False),
    (7, False),
])
def test_valid_path(pico, path, ok):
    assert pico.ota.valid_path(path) is ok


def good_manifest():
    return {"version": "abc", "url": "http://10.0.0.1:8081/",
            "files": [{"path": "controller.py", "sha256": "a" * 64, "size": 10}]}


@pytest.mark.parametrize("change", [
    lambda m: m.update(version=""),
    lambda m: m.update(url="https://x/"),
    lambda m: m.update(files=[]),
    lambda m: m.update(files="controller.py"),
    lambda m: m["files"][0].update(sha256="A" * 64),
    lambda m: m["files"][0].update(sha256="a" * 63),
    lambda m: m["files"][0].update(size=-1),
    lambda m: m["files"][0].update(size=True),
    lambda m: m["files"][0].update(path="main.py"),
    lambda m: m.update(files=[{"path": "x{}.py".format(i), "sha256": "a" * 64, "size": 1} for i in range(65)]),
])
def test_invalid_manifests(pico, change):
    manifest = good_manifest()
    assert pico.ota.valid_manifest(manifest)
    change(manifest)
    assert not pico.ota.valid_manifest(manifest)
    assert not pico.ota.valid_manifest("nope")


def test_split_url(pico):
    assert pico.ota.split_url("http://10.0.0.1:8081/files/a.py") == ("10.0.0.1", 8081, "/files/a.py")
    assert pico.ota.split_url("http://host") == ("host", 80, "/")
    for bad in ("https://host/", "http://:80/", "http://host:x/"):
        with pytest.raises(pico.ota.UpdateError):
            pico.ota.split_url(bad)


def test_file_hash_and_tree_helpers(pico, tmp_path):
    (tmp_path / "a.py").write_bytes(b"hello")
    assert pico.ota.file_sha256("a.py") == hashlib.sha256(b"hello").hexdigest()
    assert pico.ota.file_sha256("missing.py") is None
    pico.ota.makedirs("x/y/z")
    pico.ota.makedirs("x/y/z")
    (tmp_path / "x" / "y" / "f.py").write_text("f")
    pico.ota.remove_tree("x")
    pico.ota.remove_tree("x")
    assert not (tmp_path / "x").exists()


def test_version_before_any_update(pico):
    assert pico.ota.current_version() == "unknown" and not pico.ota.is_pending()


# --- stage and install ----------------------------------------------------------


def test_stage_downloads_only_changed_files(pico, installed, source, serve):
    manifest = update_for(source, serve(source))
    assert [f["path"] for f in manifest["files"]] == ["controller.py", "lib/extra.py", "net.py"]
    changed = pico.ota.stage(manifest)
    assert changed == ["controller.py", "lib/extra.py"]
    assert (installed / "ota_new" / "controller.py").read_text() == "VERSION = 2\n"
    assert (installed / "controller.py").read_text() == "VERSION = 1\n"  # untouched so far


def test_damaged_download_changes_nothing(pico, installed, source, serve):
    manifest = update_for(source, serve(source))
    manifest["files"][0]["sha256"] = "0" * 64
    with pytest.raises(pico.ota.UpdateError, match="damaged"):
        pico.ota.stage(manifest)
    assert not (installed / "ota_new").exists()
    assert (installed / "controller.py").read_text() == "VERSION = 1\n"


def test_missing_file_on_server(pico, installed, source, serve):
    manifest = update_for(source, serve(source))
    manifest["files"].append({"path": "gone.py", "sha256": "a" * 64, "size": 1})
    with pytest.raises(pico.ota.UpdateError, match="404"):
        pico.ota.stage(manifest)
    assert not (installed / "ota_new").exists()


def test_unreachable_server(pico, installed, source):
    manifest = update_for(source, "http://127.0.0.1:9/")
    with pytest.raises(pico.ota.UpdateError, match="failed"):
        pico.ota.stage(manifest)


def test_install_then_confirm(pico, installed, source, serve):
    manifest = update_for(source, serve(source))
    pico.ota.install(manifest, pico.ota.stage(manifest))
    assert (installed / "controller.py").read_text() == "VERSION = 2\n"
    assert (installed / "lib" / "extra.py").read_text() == "EXTRA = 1\n"
    assert (installed / "ota_old" / "controller.py").read_text() == "VERSION = 1\n"
    assert not (installed / "ota_new").exists()
    state = pico.ota.read_state()
    assert state["pending"] and state["installed"] and state["previous"] == "old-version"
    assert state["new_files"] == ["lib/extra.py"]
    assert pico.ota.current_version() == manifest["version"]

    assert pico.ota.confirm() is True
    assert pico.ota.confirm() is False
    assert not (installed / "ota_old").exists()
    assert pico.ota.take_result() == ("updated", "Updated from old-version")
    assert pico.ota.take_result() is None
    assert pico.ota.current_version() == manifest["version"] and not pico.ota.is_pending()


# --- boot.py rollback --------------------------------------------------------------


def run_boot():
    sys.modules.pop("boot", None)
    importlib.import_module("boot")


def test_boot_rolls_back_after_three_failed_starts(pico, installed, source, serve):
    manifest = update_for(source, serve(source))
    pico.ota.install(manifest, pico.ota.stage(manifest))
    for starts in (1, 2, 3):
        run_boot()
        assert pico.ota.read_state()["boots"] == starts
        assert (installed / "controller.py").read_text() == "VERSION = 2\n"
    run_boot()  # the fourth start: give up on the new version
    assert (installed / "controller.py").read_text() == "VERSION = 1\n"
    assert not (installed / "lib" / "extra.py").exists()  # added by the update, so removed
    assert (installed / "net.py").read_text() == "NET = 2\n"
    state = pico.ota.read_state()
    assert state["version"] == "old-version" and not state["pending"]
    result, detail = pico.ota.take_result()
    assert result == "rolled_back" and manifest["version"] in detail


def test_boot_undoes_an_interrupted_swap(pico, installed, source, serve):
    manifest = update_for(source, serve(source))
    changed = pico.ota.stage(manifest)
    real_rename = pico.ota.os.rename

    def power_cut(src, dst):
        if src == "ota_new/controller.py":  # the old file is already moved away
            raise KeyboardInterrupt("power cut")
        real_rename(src, dst)

    pico.ota.os.rename = power_cut
    try:
        with pytest.raises(KeyboardInterrupt):
            pico.ota.install(manifest, changed)
    finally:
        pico.ota.os.rename = real_rename
    assert not (installed / "controller.py").exists()  # half-way: moved to ota_old only
    run_boot()
    assert (installed / "controller.py").read_text() == "VERSION = 1\n"
    assert pico.ota.current_version() == "old-version"


def test_boot_does_nothing_normally(pico, installed):
    run_boot()
    assert pico.ota.read_state() == {"version": "old-version", "pending": False}


def test_boot_and_ota_agree_on_limits(pico):
    run_boot()
    boot = sys.modules["boot"]
    assert boot.MAX_BOOTS == pico.ota.MAX_BOOTS
    assert boot.STATE_FILE == pico.ota.STATE_FILE and boot.BACKUP_DIR == pico.ota.BACKUP_DIR


# --- the controller -----------------------------------------------------------


@pytest.fixture
def device(pico, config):
    FakeClient.instances = []
    FakeClient.fail_connect = False
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan, client_factory=FakeClient)
    resets = []
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), net, FakeClock(), reset=lambda: resets.append(True),
    )
    controller.resets = resets
    controller.start()
    return controller


def firmware_reports(device):
    return [json.loads(body) for topic, body, retain in FakeClient.instances[-1].published
            if topic == "greenhouse/1/firmware" and retain]


def test_controller_subscribes_and_reports_version(device, installed):
    device.tick()
    assert ("subscribe", "greenhouse/1/firmware/update") in FakeClient.instances[-1].calls
    (report,) = firmware_reports(device)
    assert (report["version"], report["state"]) == ("old-version", "running")


def test_controller_applies_update_from_mqtt(device, installed, source, serve):
    device.tick()
    manifest = update_for(source, serve(source))
    FakeClient.instances[-1].incoming.append((b"greenhouse/1/firmware/update", json.dumps(manifest).encode()))
    device.tick()  # received and kept
    device.tick()  # applied
    assert device.resets == [True]
    states = [r["state"] for r in firmware_reports(device)]
    assert states == ["running", "updating", "restarting"]
    assert (installed / "controller.py").read_text() == "VERSION = 2\n"


def test_controller_reports_failed_update(device, installed, source, serve):
    manifest = update_for(source, serve(source))
    manifest["files"][0]["sha256"] = "0" * 64
    assert device.apply_update(manifest) == "failed"
    assert device.resets == []
    last = firmware_reports(device)[-1]
    assert last["state"] == "failed" and "damaged" in last["detail"]
    assert (installed / "controller.py").read_text() == "VERSION = 1\n"


def test_controller_ignores_invalid_or_current_updates(device, installed):
    assert device.handle_firmware({"version": "x"}) is False
    assert firmware_reports(device)[-1]["state"] == "failed"
    manifest = good_manifest()
    manifest["version"] = "old-version"
    assert device.apply_update(manifest) == "current"


def test_new_version_confirmed_when_broker_reached(pico, installed, source, serve, config):
    manifest = update_for(source, serve(source))
    pico.ota.install(manifest, pico.ota.stage(manifest))
    run_boot()
    FakeClient.instances = []
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan, client_factory=FakeClient)
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), net, FakeClock(), reset=lambda: None)
    assert controller.update_on_trial
    controller.start()
    controller.tick()
    assert not controller.update_on_trial and not pico.ota.is_pending()
    report = firmware_reports(controller)[-1]
    assert (report["version"], report["state"]) == (manifest["version"], "updated")


def test_unconfirmed_version_restarts_after_ten_minutes(pico, installed, source, serve, config, ticks):
    manifest = update_for(source, serve(source))
    pico.ota.install(manifest, pico.ota.stage(manifest))
    resets = []
    FakeClient.instances = []
    FakeClient.fail_connect = True  # the new code can't reach the broker
    wlan = FakeWLAN()
    wlan.connected = True
    net = pico.net.Network(config, wlan=wlan, client_factory=FakeClient)
    controller = pico.controller.Controller(
        config, pico.display.Display(config, lcd=FakeLcd()), FakeSensors(),
        pico.relays.Relays(config), FakeButtons(), net, FakeClock(), reset=lambda: resets.append(True))
    controller.clock.local_minutes = lambda: 600  # local mode starts while the broker is away
    controller.start()
    for _ in range(9):
        ticks.advance(60_000)
        controller.tick()
    assert resets == []
    ticks.advance(120_000)
    controller.tick()
    assert resets == [True]
    FakeClient.fail_connect = False


# --- server and controller agree --------------------------------------------------


def test_real_code_manifest_is_accepted_by_the_controller(pico):
    manifest = firmware.manifest(url="http://192.168.1.20:8081/")
    assert pico.ota.valid_manifest(manifest)
    paths = [f["path"] for f in manifest["files"]]
    assert "main.py" not in paths and "boot.py" not in paths
    assert {"controller.py", "ota.py", "provision.py", "lib/umqtt/simple.py"} <= set(paths)
    assert not any(p.endswith(".json") for p in paths)


def test_full_update_of_the_real_code(pico, tmp_path, serve):
    """An empty controller ends up with exactly the server's files."""
    manifest = firmware.manifest(url=serve(PICO_DIR))
    changed = pico.ota.stage(manifest)
    pico.ota.install(manifest, changed)
    for entry in manifest["files"]:
        expected = (PICO_DIR / entry["path"]).read_bytes().replace(b"\r\n", b"\n")
        assert (tmp_path / entry["path"]).read_bytes() == expected
    assert pico.ota.current_version() == manifest["version"]
