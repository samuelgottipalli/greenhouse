"""
Setup codes: how a controller learns where the server is and how to log in.

The dashboard (Settings › Controllers) shows each controller's code and a QR
code. On the controller's setup page (``picoside/device/provision.py``, which
decodes it) the code fills in the broker address, port, login, controller
number and time zone, so nobody has to type an IP address on a phone.

A code is ``GH1-`` followed by URL-safe base64 (no padding) of compact JSON:
``h`` broker host, ``p`` port, ``u``/``w`` broker login (left out when the
broker has no logins), ``d`` device ID and ``z`` time zone; for an encrypted
broker (e.g. a cloud MQTT service) also ``t`` = 1 and ``c``, the name of the
root certificate the controller checks it with (``core/broker_tls.py``).
"""
import base64
import json
import socket

from core import settings

PREFIX = "GH1-"
SETUP_PAGE = "http://192.168.4.1/"
LOCAL_NAMES = ("localhost", "127.0.0.1", "::1", "")


def encode(host: str, port: int, device_id: int, user: str | None = None,
           password: str | None = None, zone: str | None = None, tls: bool = False,
           ca: str | None = None) -> str:
    """
    Build a setup code.

    Args:
        host (str): Broker address as the controller must use it (a LAN IP).
        port (int): Broker port.
        device_id (int): Controller number.
        user (str | None): Broker login name.
        password (str | None): Broker password.
        zone (str | None): IANA time zone to suggest.
        tls (bool): The broker needs an encrypted connection.
        ca (str | None): Root certificate name for ``tls`` (None: the
            controller tries its roots until one fits).

    Returns:
        str: e.g. ``"GH1-eyJoIjoi..."``.
    """
    data = {"h": host, "p": int(port), "d": int(device_id)}
    if user:
        data["u"] = user
        data["w"] = password or ""
    if zone:
        data["z"] = zone
    if tls:
        data["t"] = 1
        if ca:
            data["c"] = ca
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
    The address controllers use to reach this server (for software updates).

    Returns:
        str | None: ``PUBLIC_HOST`` if set, otherwise the detected LAN
        address; None if it can't be worked out.
    """
    return settings.PUBLIC_HOST or lan_address()


def broker_is_remote() -> bool:
    """Tell whether ``MQTT_HOST`` is another machine (e.g. a cloud MQTT service)."""
    return settings.MQTT_HOST not in LOCAL_NAMES and not settings.MQTT_HOST.startswith("127.")


def broker_address() -> str | None:
    """
    The broker address controllers use (what the setup code holds).

    Returns:
        str | None: ``MQTT_HOST`` when the broker is another machine (a cloud
        service, say); otherwise this server's address (:func:`server_address`).
    """
    return settings.MQTT_HOST if broker_is_remote() else server_address()


def setup_link(code: str) -> str:
    """
    The setup page address with the code filled in (what the QR code holds).

    Args:
        code (str): Setup code.

    Returns:
        str: e.g. ``"http://192.168.4.1/?code=GH1-..."``.
    """
    return f"{SETUP_PAGE}?code={code}"


def qr_png(text: str) -> bytes:
    """
    Draw a QR code as a PNG image (dark on white, so phones read it in either theme).

    Args:
        text (str): Content, e.g. a setup link.

    Returns:
        bytes: PNG data.
    """
    import io

    import segno

    buffer = io.BytesIO()
    segno.make(text, error="m").save(buffer, kind="png", scale=8, border=3, dark="#1d2b1f", light="#ffffff")
    return buffer.getvalue()
