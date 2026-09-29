"""
Which root certificate a controller needs for an encrypted (TLS) broker.

A controller can only verify a broker against the roots it carries in
``picoside/device/certs/`` (see ``scripts/update_controller_certs.py``).
:func:`find_root` works out which of them the broker's certificate chains
to, the same way the controller will check it: a TLS handshake that trusts
only that one root and checks the name. The name goes into the setup code
(``c``) so the controller doesn't have to try them all.
"""
import re
import socket
import ssl
from pathlib import Path

from core import settings

CERT_DIR: Path = settings.SERVER_DIR.parent / "picoside" / "device" / "certs"
# Tried first (most hosted MQTT services use one of these); the rest follow by name.
# picoside/device/net.py uses the same order.
PREFERRED: tuple[str, ...] = ("isrg_root_x1", "amazon_root_ca_1", "digicert_global_root_g2")
PEM_BLOCK = re.compile(r"-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----")


def bundled_roots(folder: Path | None = None) -> dict[str, str]:
    """
    The roots the controller carries, in the order it tries them.

    Args:
        folder (Path | None): Certificate folder (default ``CERT_DIR``).

    Returns:
        dict[str, str]: Name (file stem) to PEM text.
    """
    folder = folder or CERT_DIR
    found = {}
    for path in sorted(folder.glob("*.py")):
        block = PEM_BLOCK.search(path.read_text(encoding="utf-8"))
        if block:
            found[path.stem] = block.group(0)
    ordered = {name: found[name] for name in PREFERRED if name in found}
    ordered.update({name: pem for name, pem in found.items() if name not in ordered})
    return ordered


def handshake(host: str, port: int, pem: str | None, timeout: float = 10.0) -> None:
    """
    Make one TLS connection, trusting only ``pem`` (or the system's roots when None).

    Args:
        host (str): Broker address.
        port (int): Broker port.
        pem (str | None): Root certificate.
        timeout (float): Seconds for the connection.

    Raises:
        ssl.SSLCertVerificationError: If the broker's certificate doesn't chain to it.
        OSError: If the broker can't be reached.
    """
    context = ssl.create_default_context(cadata=pem) if pem else ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=host):
            pass


def find_root(host: str, port: int, folder: Path | None = None, timeout: float = 10.0) -> str | None:
    """
    Find which bundled root a broker's certificate chains to.

    Args:
        host (str): Broker address.
        port (int): TLS port (usually 8883).
        folder (Path | None): Certificate folder.
        timeout (float): Seconds per connection.

    Returns:
        str | None: The root's name, or None if none of them fits (the
        controller then can't verify this broker).

    Raises:
        OSError: If the broker can't be reached, or doesn't speak TLS.
    """
    for name, pem in bundled_roots(folder).items():
        try:
            handshake(host, port, pem, timeout)
        except ssl.SSLCertVerificationError:
            continue
        return name
    return None
