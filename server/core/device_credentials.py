"""
Broker logins of the controllers, kept so the dashboard can show setup codes.

Mosquitto stores only password hashes, so the plain passwords live in
``server/data/device_credentials.json`` (git-ignored, readable by the owner
only), written by the installer or from the Controllers page. The file maps
device IDs to ``{"user": ..., "password": ...}``.
"""
import json
import os
import secrets
from pathlib import Path

from core import settings

CREDENTIALS_FILE: Path = settings.SERVER_DIR / "data" / "device_credentials.json"


def device_user(device_id: int) -> str:
    """
    The standard broker login name of a controller.

    Args:
        device_id (int): Controller number.

    Returns:
        str: e.g. ``"greenhouse-device-1"`` (matches deploy/mosquitto/greenhouse.acl).
    """
    return f"greenhouse-device-{int(device_id)}"


def new_password() -> str:
    """
    Make a random broker password.

    Returns:
        str: 20 URL-safe characters (easy to copy, no quoting problems).
    """
    return secrets.token_urlsafe(15)


def load(path: Path | None = None) -> dict[int, dict]:
    """
    Read every stored login.

    Args:
        path (Path | None): File to read (default ``CREDENTIALS_FILE``).

    Returns:
        dict[int, dict]: Device ID -> ``{"user", "password"}``; empty if none.
    """
    path = path or CREDENTIALS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {int(k): v for k, v in raw.items() if str(k).isdigit() and isinstance(v, dict)}


def get(device_id: int, path: Path | None = None) -> dict | None:
    """
    Read one controller's login.

    Args:
        device_id (int): Controller number.
        path (Path | None): File to read.

    Returns:
        dict | None: ``{"user", "password"}``, or None if not stored.
    """
    return load(path).get(int(device_id))


def save(device_id: int, user: str, password: str, path: Path | None = None) -> None:
    """
    Store (or replace) one controller's login.

    The file is replaced in one step and made readable by its owner only.

    Args:
        device_id (int): Controller number.
        user (str): Broker login name.
        password (str): Broker password.
        path (Path | None): File to write.
    """
    path = path or CREDENTIALS_FILE
    data = {str(k): v for k, v in load(path).items()}
    data[str(int(device_id))] = {"user": user, "password": password}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
