"""
Set up a Pico W controller over USB, for the installer wizard.

1. **Find it.** A new Pico held in BOOTSEL mode shows up as a USB drive
   (``RPI-RP2``, or ``RP2350`` for a Pico 2 W); one that already runs
   MicroPython shows up as a serial port (USB vendor ``0x2E8A``).
2. **Install MicroPython** on a BOOTSEL drive: download the newest ``.uf2``
   for the board from micropython.org and copy it onto the drive.
3. **Copy the controller code** with ``mpremote``: every file in
   ``picoside/device`` (with LF line endings, as over-the-air updates send
   them), plus ``config.json`` (Wi-Fi, broker, time zone), ``firmware.json``
   (so the dashboard knows the version) and ``wifi_unverified`` (so a wrong
   Wi-Fi password brings up the setup hotspot instead of silence).
   The board is restarted first: its watchdog only starts once the
   controller has connected, so the copy isn't cut short.
4. **Wait** for the controller to report ``online`` to the broker.

Also works out which Wi-Fi network this computer is on, so the wizard can
suggest it, and whether it is a 5 GHz network (the Pico W can't use those).
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from installer.steps import REPO_DIR, server_import_path, system

PICO_VENDOR_ID = 0x2E8A
DEVICE_DIR = REPO_DIR / "picoside" / "device"
DOWNLOAD_PAGES = {
    "RPI_PICO_W": "https://micropython.org/download/RPI_PICO_W/",
    "RPI_PICO2_W": "https://micropython.org/download/RPI_PICO2_W/",
}
FALLBACK_UF2 = {
    "RPI_PICO_W": "https://micropython.org/resources/firmware/RPI_PICO_W-20260824-v1.29.0.uf2",
    "RPI_PICO2_W": "https://micropython.org/resources/firmware/RPI_PICO2_W-20260824-v1.29.0.uf2",
}
EXTRA_FILES = ("boot.py", "main.py")


# --- finding the board ---------------------------------------------------------


def drive_candidates(os_name: str | None = None) -> list[Path]:
    """
    Places a BOOTSEL drive may be mounted.

    Returns:
        list[Path]: Drive roots to check for ``INFO_UF2.TXT``.
    """
    os_name = os_name or system()
    if os_name == "windows":
        return [Path(f"{letter}:\\") for letter in "DEFGHIJKLMNOPQRSTUVWXYZ"]
    if os_name == "macos":
        return [Path("/Volumes/RPI-RP2"), Path("/Volumes/RP2350")]
    user = Path.home().name
    return [Path(base) / user / name for base in ("/media", "/run/media") for name in ("RPI-RP2", "RP2350")]


def board_of(info_text: str) -> str:
    """
    Name the MicroPython build for a BOOTSEL drive.

    Args:
        info_text (str): Contents of the drive's ``INFO_UF2.TXT``.

    Returns:
        str: ``"RPI_PICO2_W"`` for an RP2350 board, else ``"RPI_PICO_W"``.
    """
    return "RPI_PICO2_W" if "RP2350" in info_text else "RPI_PICO_W"


def find_bootsel(candidates: list[Path] | None = None) -> tuple[Path, str] | None:
    """
    Find a Pico waiting in BOOTSEL mode.

    Args:
        candidates (list[Path] | None): Drive roots (default: :func:`drive_candidates`).

    Returns:
        tuple[Path, str] | None: The drive and the board name, or None.
    """
    for drive in candidates if candidates is not None else drive_candidates():
        info = drive / "INFO_UF2.TXT"
        try:
            text = info.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "RPI-RP2" in text or "RP2350" in text:
            return drive, board_of(text)
    return None


def find_serial_ports(list_ports=None) -> list[str]:
    """
    Find Picos running MicroPython.

    Args:
        list_ports (callable | None): ``serial.tools.list_ports.comports`` (injected in tests).

    Returns:
        list[str]: Serial port names, e.g. ``["COM5"]`` or ``["/dev/ttyACM0"]``.
    """
    if list_ports is None:
        from serial.tools.list_ports import comports as list_ports
    return [port.device for port in list_ports() if getattr(port, "vid", None) == PICO_VENDOR_ID]


# --- MicroPython ---------------------------------------------------------------


def latest_uf2_url(board: str, fetch=None) -> str:
    """
    The newest MicroPython release for a board.

    Args:
        board (str): ``"RPI_PICO_W"`` or ``"RPI_PICO2_W"``.
        fetch (callable | None): ``fetch(url) -> bytes`` (injected in tests).

    Returns:
        str: Download address (a known release if the page can't be read).
    """
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=15).read())
    try:
        page = fetch(DOWNLOAD_PAGES[board]).decode("utf-8", "replace")
    except OSError:
        return FALLBACK_UF2[board]
    pattern = r"/resources/firmware/" + board + r"-(\d{8})-v[\d.]+\.uf2"
    found = sorted(set(re.finditer(pattern, page)), key=lambda m: m.group(1), reverse=True)
    return "https://micropython.org" + found[0].group(0) if found else FALLBACK_UF2[board]


def flash_micropython(drive: Path, uf2: bytes) -> Path:
    """
    Copy MicroPython onto a BOOTSEL drive (the Pico restarts by itself).

    Args:
        drive (Path): BOOTSEL drive root.
        uf2 (bytes): Firmware file.

    Returns:
        Path: The file written.
    """
    target = drive / "firmware.uf2"
    with open(target, "wb") as f:
        f.write(uf2)
    return target


# --- Wi-Fi of this computer ------------------------------------------------------


def parse_netsh(text: str) -> tuple[str | None, bool | None]:
    """Read the SSID and band from ``netsh wlan show interfaces`` (Windows)."""
    ssid = channel = None
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "SSID" and value:
            ssid = value
        elif key == "Channel" and value.isdigit():
            channel = int(value)
    return ssid, (channel > 14 if channel else None)


def parse_nmcli(text: str) -> tuple[str | None, bool | None]:
    """Read the SSID and band from ``nmcli -t -f active,ssid,chan dev wifi`` (Linux)."""
    for line in text.splitlines():
        parts = line.rsplit(":", 1)
        if len(parts) == 2 and parts[0].startswith("yes:"):
            ssid, channel = parts[0][4:].replace("\\:", ":"), parts[1]
            return ssid or None, (int(channel) > 14 if channel.isdigit() else None)
    return None, None


def parse_airport(text: str) -> tuple[str | None, bool | None]:
    """Read the SSID from ``networksetup -getairportnetwork en0`` (macOS)."""
    _, sep, ssid = text.strip().partition("Current Wi-Fi Network: ")
    return (ssid.strip() or None) if sep else None, None


def current_wifi(os_name: str | None = None, run=subprocess.run) -> tuple[str | None, bool | None]:
    """
    Which Wi-Fi network this computer uses.

    Args:
        os_name (str | None): ``"windows"``, ``"macos"`` or ``"linux"``.
        run (callable): ``subprocess.run`` (injected in tests).

    Returns:
        tuple[str | None, bool | None]: Network name, and whether it is 5 GHz
        (None when unknown). ``(None, None)`` if it can't be found.
    """
    os_name = os_name or system()
    commands = {
        "windows": (["netsh", "wlan", "show", "interfaces"], parse_netsh),
        "linux": (["nmcli", "-t", "-f", "active,ssid,chan", "dev", "wifi"], parse_nmcli),
        "macos": (["networksetup", "-getairportnetwork", "en0"], parse_airport),
    }
    command, parse = commands[os_name]
    try:
        result = run(command, capture_output=True, text=True, timeout=10, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None, None
    return parse(result.stdout or "")


# --- the controller's files ------------------------------------------------------


def controller_config(answers: dict, base: dict | None = None) -> tuple[dict, str | None]:
    """
    Build ``config.json`` for the controller.

    Args:
        answers (dict): ``wifi_ssid``, ``wifi_password``, ``mqtt_broker``,
            ``mqtt_port``, ``mqtt_user``, ``mqtt_password``, ``device_id`` and
            ``timezone``.
        base (dict | None): Starting values (default: ``config.example.json``).

    Returns:
        tuple[dict, str | None]: The config, and a time-zone warning if the
        controller can't follow that zone's daylight saving exactly.
    """
    sys.path.insert(0, str(REPO_DIR / "picoside"))
    try:
        import setup_config
    finally:
        sys.path.remove(str(REPO_DIR / "picoside"))
    base = base or json.loads(setup_config.EXAMPLE_FILE.read_text(encoding="utf-8"))
    return setup_config.build_config(base, answers)


def stage_files(config: dict, folder: Path) -> list[str]:
    """
    Put everything the controller needs into a folder, laid out as on the Pico.

    Args:
        config (dict): Output of :func:`controller_config`.
        folder (Path): Empty folder.

    Returns:
        list[str]: Relative paths written (folders before the files in them).
    """
    server_import_path()
    from core import firmware

    manifest = firmware.manifest(DEVICE_DIR, url="")
    paths = [entry["path"] for entry in manifest["files"]] + list(EXTRA_FILES)
    for relative in paths:
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(firmware.file_bytes(DEVICE_DIR, relative))
    extras = {
        "config.json": json.dumps(config),
        "firmware.json": json.dumps({"version": manifest["version"], "pending": False}),
        "wifi_unverified": "1",
    }
    for name, text in extras.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
    return sorted(paths) + list(extras)


def folders_of(paths: list[str]) -> list[str]:
    """The folders the files need, parents first (e.g. ``lib``, ``lib/umqtt``)."""
    folders = set()
    for path in paths:
        parts = path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            folders.add("/".join(parts[:depth]))
    return sorted(folders, key=lambda f: (f.count("/"), f))


def mpremote(port: str, *args: str) -> list[str]:
    """An ``mpremote`` command for one board."""
    return [sys.executable, "-m", "mpremote", "connect", port, *args]


def copy_command(port: str, folder: Path, paths: list[str]) -> list[str]:
    """
    One ``mpremote`` command that makes the folders, copies every file,
    clears any half-finished update and restarts the board.

    Args:
        port (str): Serial port.
        folder (Path): Staged files (:func:`stage_files`).
        paths (list[str]): Relative paths to copy.

    Returns:
        list[str]: Command line.
    """
    setup = ("import os\n"
             "def rm(p):\n"
             " try:\n"
             "  if os.stat(p)[0] & 0x4000:\n"
             "   [rm(p + '/' + n) for n in os.listdir(p)]\n"
             "   os.rmdir(p)\n"
             "  else:\n"
             "   os.remove(p)\n"
             " except OSError:\n"
             "  pass\n"
             "rm('ota_new')\nrm('ota_old')\n")
    for name in folders_of(paths):
        setup += f"try:\n os.mkdir('{name}')\nexcept OSError:\n pass\n"
    command = mpremote(port, "exec", setup)
    for path in paths:
        command += ["+", "fs", "cp", str(folder / path), ":" + path]
    return command + ["+", "reset"]


def reset_command(port: str) -> list[str]:
    """Restart the board (stops a running controller before its watchdog starts)."""
    return mpremote(port, "reset")


def wait_for_port(timeout: float = 20.0, find=find_serial_ports, sleep=time.sleep,
                  clock=time.monotonic) -> str | None:
    """
    Wait for a Pico's serial port to appear (after a restart or flashing).

    Returns:
        str | None: The port, or None on timeout.
    """
    deadline = clock() + timeout
    while clock() < deadline:
        ports = find()
        if ports:
            return ports[0]
        sleep(0.5)
    return None


def wait_online(device_id: int, host: str, port: int, user: str | None, password: str | None,
                prefix: str = "greenhouse", timeout: float = 120.0, client_factory=None) -> bool:
    """
    Wait until the controller reports ``online`` to the broker.

    Args:
        device_id (int): Controller number.
        host (str): Broker address.
        port (int): Broker port.
        user (str | None): Server login.
        password (str | None): Server password.
        prefix (str): Topic prefix.
        timeout (float): Seconds to wait.
        client_factory (callable | None): Builds a paho client (injected in tests).

    Returns:
        bool: True once it is online.
    """
    import threading

    if client_factory is None:
        from paho.mqtt.client import CallbackAPIVersion, Client

        client_factory = lambda: Client(CallbackAPIVersion.VERSION2, client_id="greenhouse-installer-wait")  # noqa: E731
    client = client_factory()
    if user:
        client.username_pw_set(user, password)
    online = threading.Event()
    topic = f"{prefix}/{device_id}/status"

    def on_connect(c, _userdata, _flags, _reason, _properties=None):
        c.subscribe(topic)

    def on_message(_c, _userdata, message):
        if message.payload.decode("utf-8", "replace").strip() == "online":
            online.set()

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(host, port, keepalive=30)
    except OSError:
        return False
    client.loop_start()
    try:
        return online.wait(timeout)
    finally:
        client.loop_stop()
        client.disconnect()


def staging_folder() -> Path:
    """A new private temporary folder for the controller's files."""
    return Path(tempfile.mkdtemp(prefix="greenhouse-pico-"))


def remove_folder(folder: Path) -> None:
    """Delete a staging folder (it holds the Wi-Fi password)."""
    shutil.rmtree(folder, ignore_errors=True)
