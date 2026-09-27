"""
Setup codes: how a controller learns where the server is and how to log in.

The dashboard (Settings, Controllers) shows each controller's code and a QR
code. On the controller's setup page (``picoside/device/provision.py``, which
decodes it) the code fills in the broker address, port, login, controller
number and time zone, so nobody has to type an IP address on a phone.

A code is ``GH1-`` followed by URL-safe base64 (no padding) of compact JSON:
``h`` broker host, ``p`` port, ``u``/``w`` broker login (left out when the
broker has no logins), ``d`` device ID and ``z`` time zone.
"""
import base64
import json
import socket

from core import settings

PREFIX = "GH1-"
SETUP_PAGE = "http://192.168.4.1/"
LOCAL_NAMES = ("localhost", "127.0.0.1", "::1", "")


def encode(host: str, port: int, device_id: int, user: str | None = None,
           password: str | None = None, zone: str | None = None) -> str:
    """
    Build a setup code.

    Args:
        host (str): Broker address as the controller must use it (a LAN IP).
        port (int): Broker port.
        device_id (int): Controller number.
        user (str | None): Broker login name.
        password (str | None): Broker password.
        zone (str | None): IANA time zone to suggest.

    Returns:
        str: e.g. ``"GH1-eyJoIjoi..."``.
    """
    data = {"h": host, "p": int(port), "d": int(device_id)}
    if user:
        data["u"] = user
        data["w"] = password or ""
    if zone:
        data["z"] = zone
    body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")


def lan_address() -> str | None:
    """
    Find this computer's address on the local network.

    Opens a UDP socket towards a private address (nothing is sent) and reads
    which local address the system picked.

    Returns:
        str | None: e.g. ``"192.168.1.20"``, or None when there is no network.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.254.254.254", 1))
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") or address == "0.0.0.0" else address


def server_address() -> str | None:
    """
    The address controllers use to reach this server.

    ``PUBLIC_HOST`` if set; otherwise ``MQTT_HOST`` unless it only means
    "this computer"; otherwise the detected LAN address.

    Returns:
        str | None: Host name or IP, or None if it can't be worked out.
    """
    if settings.PUBLIC_HOST:
        return settings.PUBLIC_HOST
    if settings.MQTT_HOST not in LOCAL_NAMES and not settings.MQTT_HOST.startswith("127."):
        return settings.MQTT_HOST
    return lan_address()


def setup_link(code: str) -> str:
    """
    The setup page address with the code filled in (what the QR code holds).

    Args:
        code (str): Setup code.

    Returns:
        str: e.g. ``"http://192.168.4.1/?code=GH1-..."``.
    """
    return f"{SETUP_PAGE}?code={code}"


def qr_svg(text: str) -> str:
    """
    Draw a QR code.

    Args:
        text (str): Content, e.g. a setup link.

    Returns:
        str: SVG markup (scalable, dark on white).
    """
    import segno

    return segno.make(text, error="m").svg_inline(scale=6, border=2, dark="#1d2b1f", light="#ffffff")
