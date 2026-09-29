"""
Refresh the root certificates the controller uses to check cloud MQTT brokers.

The controller (``picoside/device/net.py``) can only verify a broker's
certificate against roots it carries. This writes a small, common set of
them, taken from ``certifi`` (Mozilla's list), to
``picoside/device/certs/<name>.py`` as text: each file holds one PEM
certificate in a ``PEM`` string. They are ``.py`` files so over-the-air
updates carry them (controllers from 1.0.0 only accept ``.py`` files); the
controller reads them as text rather than importing them.

``ROOTS`` is in the order the controller tries them when it doesn't yet know
which one its broker uses. Root certificates last many years; run this when
a hosted MQTT service's root isn't in the list, or once a year.

Run from ``server/``::

    python -m scripts.update_controller_certs
"""
import re
import sys
from pathlib import Path

import certifi

CERT_DIR: Path = Path(__file__).resolve().parents[2] / "picoside" / "device" / "certs"

# File name -> (certifi label, who uses it).
ROOTS: dict[str, tuple[str, str]] = {
    "isrg_root_x1": ("ISRG Root X1", "Let's Encrypt: HiveMQ Cloud, many others"),
    "amazon_root_ca_1": ("Amazon Root CA 1", "Amazon: AWS IoT, HiveMQ's public broker"),
    "digicert_global_root_g2": ("DigiCert Global Root G2", "DigiCert: EMQX Cloud, Azure"),
    "usertrust_rsa": ("USERTrust RSA Certification Authority", "Sectigo"),
    "globalsign_root_r6": ("GlobalSign Root CA - R6", "GlobalSign: flespi"),
    "globalsign_root_r3": ("GlobalSign Root CA - R3", "GlobalSign"),
    "gts_root_r1": ("GTS Root R1", "Google Trust Services"),
    "isrg_root_x2": ("ISRG Root X2", "Let's Encrypt (ECDSA)"),
    "amazon_root_ca_3": ("Amazon Root CA 3", "Amazon (ECDSA)"),
    "gts_root_r4": ("GTS Root R4", "Google Trust Services (ECDSA)"),
    "microsoft_rsa_2017": ("Microsoft RSA Root Certificate Authority 2017", "Microsoft: Azure Event Grid"),
}

TEMPLATE = '''"""
{label}. Used by {users}.

A root certificate the controller checks MQTT brokers against (read as text
by net.py, not imported). Written by server/scripts/update_controller_certs.py
from certifi; don't edit by hand.
"""

PEM = """
{pem}
"""
'''


def certifi_roots(bundle: Path | None = None) -> dict[str, str]:
    """
    Read Mozilla's roots from certifi.

    Args:
        bundle (Path | None): A ``cacert.pem`` (default: certifi's).

    Returns:
        dict[str, str]: Label to PEM text.
    """
    text = Path(bundle or certifi.where()).read_text(encoding="ascii")
    pattern = r'# Label: "([^"]+)"[\s\S]*?(-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----)'
    return dict(re.findall(pattern, text))


def file_text(name: str, pem: str) -> str:
    """The contents of ``certs/<name>.py`` for one root."""
    label, users = ROOTS[name]
    return TEMPLATE.format(label=label, users=users, pem=pem.strip())


def write_all(folder: Path = CERT_DIR, bundle: Path | None = None) -> list[str]:
    """
    Write every root in ``ROOTS`` and remove files for roots no longer listed.

    Args:
        folder (Path): Where to write (default: the controller's ``certs/``).
        bundle (Path | None): A ``cacert.pem`` (default: certifi's).

    Returns:
        list[str]: Names written, in ``ROOTS`` order.

    Raises:
        KeyError: If certifi no longer has one of the roots.
    """
    roots = certifi_roots(bundle)
    folder.mkdir(parents=True, exist_ok=True)
    for name, (label, _users) in ROOTS.items():
        (folder / f"{name}.py").write_text(file_text(name, roots[label]), encoding="utf-8", newline="\n")
    for old in folder.glob("*.py"):
        if old.stem not in ROOTS:
            old.unlink()
    return list(ROOTS)


def main() -> int:
    names = write_all()
    print(f"Wrote {len(names)} root certificates to {CERT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
