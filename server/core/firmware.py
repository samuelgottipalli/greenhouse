"""
The controller code the server offers as over-the-air updates.

The code lives in ``picoside/device/`` of this checkout, so pulling a newer
version of the project (or the installer's update step) makes a new
controller version available. :func:`manifest` lists every updatable file
with its SHA-256 and size. Each version has a *build*, a hash over that list
that changes whenever any file does (sent as ``version``, the key 1.0.0
controllers compare), and a *name* people read, like ``1.1.0``, from
``picoside/device/version.py`` (sent as ``name``). ``services/firmware_server.py`` serves the
files and :func:`publish_update` tells a controller to fetch them (see
docs/MQTT.md, "Over-the-air updates", and ``picoside/device/ota.py``).
"""
import hashlib
import json
import logging
import re
from pathlib import Path

from paho.mqtt.publish import single

from core import settings, setup_code
from core.mqtt import connection, device_topic

log = logging.getLogger(__name__)

DEVICE_DIR: Path = settings.SERVER_DIR.parent / "picoside" / "device"
# Never sent over the air: the loader and rollback guard, and settings files.
NOT_UPDATED: tuple[str, ...] = ("boot.py", "main.py")
OLDEST_NAME = "1.0.0"  # controllers from before version names; they report none


def updatable_files(device_dir: Path | None = None) -> list[str]:
    """
    List the controller files an update may replace.

    Args:
        device_dir (Path | None): Controller code folder (default ``DEVICE_DIR``).

    Returns:
        list[str]: Relative POSIX paths of ``.py`` files, sorted, without
        ``NOT_UPDATED`` files and caches.
    """
    root = device_dir or DEVICE_DIR
    paths = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root).as_posix()
        if relative in NOT_UPDATED or "__pycache__" in relative:
            continue
        paths.append(relative)
    return sorted(paths)


def file_bytes(root: Path, relative: str) -> bytes:
    """
    Read a controller file as it is sent: with LF line endings.

    A Windows checkout has CRLF endings; normalising them gives the same
    version on every server for the same code.

    Args:
        root (Path): Controller code folder.
        relative (str): POSIX path inside it.

    Returns:
        bytes: File content.
    """
    return (root / relative).read_bytes().replace(b"\r\n", b"\n")


def file_entry(root: Path, relative: str) -> dict:
    """
    Describe one file for the manifest.

    Args:
        root (Path): Controller code folder.
        relative (str): POSIX path inside it.

    Returns:
        dict: ``path``, ``sha256`` (hex) and ``size`` (bytes).
    """
    data = file_bytes(root, relative)
    return {"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def version_of(files: list[dict]) -> str:
    """
    Name a set of files.

    Args:
        files (list[dict]): Manifest entries.

    Returns:
        str: First 12 hex digits of a SHA-256 over ``path sha256`` lines.
    """
    lines = "".join(f"{f['path']} {f['sha256']}\n" for f in sorted(files, key=lambda f: f["path"]))
    return hashlib.sha256(lines.encode("utf-8")).hexdigest()[:12]


def manifest(device_dir: Path | None = None, url: str | None = None) -> dict:
    """
    Describe the controller code on offer.

    Args:
        device_dir (Path | None): Controller code folder.
        url (str | None): Where controllers download it (default :func:`firmware_url`).

    Returns:
        dict: ``version`` (the build), ``name``, ``url`` and ``files``; see docs/MQTT.md.
    """
    root = device_dir or DEVICE_DIR
    files = [file_entry(root, relative) for relative in updatable_files(root)]
    return {"version": version_of(files), "name": available_name(root),
            "url": url if url is not None else firmware_url(), "files": files}


def available_version(device_dir: Path | None = None) -> str:
    """
    The build of the controller code in this checkout.

    Args:
        device_dir (Path | None): Controller code folder.

    Returns:
        str: 12 hex digits.
    """
    return manifest(device_dir, url="")["version"]


def available_name(device_dir: Path | None = None) -> str:
    """
    The version name of the controller code in this checkout.

    Args:
        device_dir (Path | None): Controller code folder.

    Returns:
        str: e.g. ``"1.1.0"`` from ``version.py`` (``OLDEST_NAME`` without one).
    """
    path = (device_dir or DEVICE_DIR) / "version.py"
    if not path.exists():
        return OLDEST_NAME
    found = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"), re.M)
    return found.group(1) if found else OLDEST_NAME


def installed_name(status: dict) -> str | None:
    """
    The version name a controller reported.

    Args:
        status (dict): From ``db.device_status``.

    Returns:
        str | None: Its name; ``OLDEST_NAME`` for a 1.0.0 controller (it reports
        a build but no name); None if it never reported.
    """
    if not status.get("firmware_version"):
        return None
    return status.get("firmware_name") or OLDEST_NAME


def update_available(status: dict, build: str | None = None, name: str | None = None) -> bool | None:
    """
    Tell whether this server offers a controller different code.

    Builds are compared when the controller knows its build; one set up by
    hand (build ``"unknown"``) is compared by version name.

    Args:
        status (dict): From ``db.device_status``.
        build (str | None): Build on offer (default: this checkout's).
        name (str | None): Name on offer (default: this checkout's).

    Returns:
        bool | None: None if the controller never reported its version.
    """
    installed = status.get("firmware_version")
    if not installed:
        return None
    if installed != "unknown":
        return installed != (build or available_version())
    return installed_name(status) != (name or available_name())


def firmware_url() -> str:
    """
    Address of the firmware service as controllers reach it.

    Returns:
        str: e.g. ``"http://192.168.1.20:8081/"`` (``localhost`` if the LAN
        address can't be found, which controllers can't use).
    """
    return f"http://{setup_code.server_address() or 'localhost'}:{settings.FIRMWARE_PORT}/"


def publish_update(device_id: int, update: dict | None = None) -> bool:
    """
    Ask a controller to update itself to the code in this checkout.

    Sent with QoS 1 and not retained: an offline controller doesn't get it
    (the Controllers page only offers the button while it is online).

    Args:
        device_id (int): Target controller.
        update (dict | None): Manifest to send (default: :func:`manifest`).

    Returns:
        bool: True if the broker accepted the message.
    """
    try:
        single(
            topic=device_topic(device_id, "firmware/update"),
            payload=json.dumps(update or manifest()),
            qos=1,
            **connection(),
        )
    except (OSError, ValueError) as err:
        log.error("Could not publish the update: %s", err)
        return False
    return True
