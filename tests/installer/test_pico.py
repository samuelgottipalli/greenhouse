"""Tests for installer/pico.py: finding the Pico, MicroPython, Wi-Fi, files and mpremote."""
import json
import types

import pytest

from installer import pico
from test_broker import FakeMqtt


def test_board_of():
    assert pico.board_of("UF2 Bootloader v3.0\nModel: Raspberry Pi RP2\nBoard-ID: RPI-RP2\n") == "RPI_PICO_W"
    assert pico.board_of("Model: Raspberry Pi RP2350\nBoard-ID: RP2350\n") == "RPI_PICO2_W"


def test_find_bootsel(tmp_path):
    usb, other = tmp_path / "E", tmp_path / "F"
    usb.mkdir()
    other.mkdir()
    (other / "INFO_UF2.TXT").write_text("some other board")
    assert pico.find_bootsel([tmp_path / "missing", other]) is None
    (usb / "INFO_UF2.TXT").write_text("Board-ID: RPI-RP2\n")
    assert pico.find_bootsel([tmp_path / "missing", other, usb]) == (usb, "RPI_PICO_W")


def test_drive_candidates():
    assert str(pico.drive_candidates("windows")[0]).startswith("D:")
    assert pico.drive_candidates("macos")[0].as_posix() == "/Volumes/RPI-RP2"
    assert all("RP" in p.name for p in pico.drive_candidates("linux"))


def test_find_serial_ports():
    ports = [types.SimpleNamespace(device="COM3", vid=0x1234), types.SimpleNamespace(device="COM5", vid=0x2E8A),
             types.SimpleNamespace(device="COM7", vid=None)]
    assert pico.find_serial_ports(lambda: ports) == ["COM5"]


def test_latest_uf2_url_picks_newest():
    page = (b'<a href="/resources/firmware/RPI_PICO_W-20251209-v1.27.0.uf2">'
            b'<a href="/resources/firmware/RPI_PICO_W-20260824-v1.29.0.uf2">'
            b'<a href="/resources/firmware/RPI_PICO_W-20260406-v1.28.0.uf2">')
    assert pico.latest_uf2_url("RPI_PICO_W", lambda url: page) == \
        "https://micropython.org/resources/firmware/RPI_PICO_W-20260824-v1.29.0.uf2"


def test_latest_uf2_url_falls_back():
    def offline(url):
        raise OSError("offline")

    assert pico.latest_uf2_url("RPI_PICO2_W", offline) == pico.FALLBACK_UF2["RPI_PICO2_W"]
    assert pico.latest_uf2_url("RPI_PICO_W", lambda url: b"nothing here") == pico.FALLBACK_UF2["RPI_PICO_W"]


def test_flash_micropython(tmp_path):
    target = pico.flash_micropython(tmp_path, b"UF2\x0a")
    assert target.read_bytes() == b"UF2\x0a" and target.suffix == ".uf2"


NETSH = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : Home Net
    BSSID                  : aa:bb:cc:dd:ee:ff
    Radio type             : 802.11ac
    Channel                : 36
"""


def test_parse_wifi_outputs():
    assert pico.parse_netsh(NETSH) == ("Home Net", True)
    assert pico.parse_netsh(NETSH.replace(": 36", ": 6")) == ("Home Net", False)
    assert pico.parse_netsh("There is no wireless interface") == (None, None)
    assert pico.parse_nmcli("no:Other:6\nyes:My\\:Net:11\n") == ("My:Net", False)
    assert pico.parse_nmcli("yes:Fast:149\n") == ("Fast", True)
    assert pico.parse_nmcli("") == (None, None)
    assert pico.parse_airport("Current Wi-Fi Network: Garden\n") == ("Garden", None)
    assert pico.parse_airport("You are not associated with an AirPort network.") == (None, None)


def test_current_wifi():
    def run(command, **kw):
        assert command[0] == "netsh"
        return types.SimpleNamespace(stdout=NETSH)

    assert pico.current_wifi("windows", run) == ("Home Net", True)

    def missing(command, **kw):
        raise FileNotFoundError(command[0])

    assert pico.current_wifi("linux", missing) == (None, None)


ANSWERS = {"wifi_ssid": "Home", "wifi_password": "wifi-pass", "mqtt_broker": "192.168.1.20", "mqtt_port": 1883,
           "mqtt_user": "greenhouse-device-2", "mqtt_password": "pw", "device_id": 2, "timezone": "Europe/Berlin"}


def test_controller_config():
    config, warning = pico.controller_config(ANSWERS)
    assert warning is None
    assert config["mqtt_client_id"] == "greenhouse-device-2"
    assert (config["utc_offset_minutes"], config["dst_rule"]) == (60, "eu")
    assert config["relay_pins"] == [17, 18, 19, 20, 21, 22, 26, 27]  # the rest from the example


def test_stage_files(tmp_path):
    from core import firmware

    config, _ = pico.controller_config(ANSWERS)
    paths = pico.stage_files(config, tmp_path)
    manifest = firmware.manifest(pico.DEVICE_DIR, url="")
    for entry in manifest["files"]:
        assert entry["path"] in paths
        assert b"\r\n" not in (tmp_path / entry["path"]).read_bytes()
    assert {"main.py", "boot.py", "config.json", "firmware.json", "wifi_unverified"} <= set(paths)
    assert json.loads((tmp_path / "config.json").read_text())["wifi_ssid"] == "Home"
    assert json.loads((tmp_path / "firmware.json").read_text()) == {"version": manifest["version"], "pending": False}
    assert not any(p.endswith(".example.json") for p in paths)


def test_folders_of():
    assert pico.folders_of(["a.py", "lib/umqtt/simple.py", "lib/x.py"]) == ["lib", "lib/umqtt"]


def test_copy_command(tmp_path):
    paths = ["controller.py", "lib/umqtt/simple.py", "config.json"]
    command = pico.copy_command("COM5", tmp_path, paths)
    assert command[1:6] == ["-m", "mpremote", "connect", "COM5", "exec"]
    setup = command[6]
    compile(setup, "setup", "exec")  # valid Python (and MicroPython) code
    assert setup.index("os.mkdir('lib')") < setup.index("os.mkdir('lib/umqtt')")
    assert "rm('ota_new')" in setup
    copies = [command[i + 1:i + 5] for i, part in enumerate(command) if part == "+" and command[i + 1] == "fs"]
    assert copies == [["fs", "cp", str(tmp_path / p), ":" + p] for p in paths]
    assert command[-2:] == ["+", "reset"]
    assert pico.reset_command("COM5")[-3:] == ["connect", "COM5", "reset"] or pico.reset_command("COM5")[-1] == "reset"


def test_setup_code_runs_on_a_board_folder(tmp_path, monkeypatch):
    """The exec snippet clears half-finished updates and makes folders (checked on CPython)."""
    (tmp_path / "ota_new" / "lib").mkdir(parents=True)
    (tmp_path / "ota_new" / "lib" / "x.py").write_text("x")
    (tmp_path / "lib").mkdir()
    monkeypatch.chdir(tmp_path)
    command = pico.copy_command("COM5", tmp_path, ["lib/umqtt/simple.py"])
    exec(command[6], {})
    assert not (tmp_path / "ota_new").exists()
    assert (tmp_path / "lib" / "umqtt").is_dir()


def test_wait_for_port():
    now = [0.0]
    answers = [[], [], ["COM5"]]
    port = pico.wait_for_port(10, find=lambda: answers.pop(0), sleep=lambda s: now.__setitem__(0, now[0] + s),
                              clock=lambda: now[0])
    assert port == "COM5"
    assert pico.wait_for_port(1, find=lambda: [], sleep=lambda s: now.__setitem__(0, now[0] + s),
                              clock=lambda: now[0]) is None


def test_wait_online():
    client = FakeMqtt(result="Success")
    client.messages = [b"offline", b"online"]
    assert pico.wait_online(2, "h", 1883, "u", "p", client_factory=lambda: client)
    assert client.subscribed == ["greenhouse/2/status"]
    silent = FakeMqtt(result="Success")
    assert not pico.wait_online(2, "h", 1883, None, None, timeout=0.01, client_factory=lambda: silent)
    assert not pico.wait_online(2, "h", 1883, None, None,
                                client_factory=lambda: FakeMqtt(error=OSError("unreachable")))


def test_staging_folder_is_removed():
    folder = pico.staging_folder()
    (folder / "config.json").write_text("{}")
    pico.remove_folder(folder)
    assert not folder.exists()
