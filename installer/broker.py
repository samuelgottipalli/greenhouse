"""
MQTT broker (Mosquitto) setup for the installer, locked down like
``deploy/mosquitto``: every client logs in, and each controller may only use
its own topics.

* **Linux** uses the system Mosquitto: one script, run as administrator
  through ``pkexec``, installs the package, writes the settings to
  ``/etc/mosquitto`` and restarts the service.
* **Windows and macOS** install Mosquitto (``winget`` / Homebrew) and keep
  its settings in ``server/data/mosquitto/``; ``server/run_all.py`` runs it.
  No administrator rights are needed after the install. If port 1883 is
  already taken (e.g. by Mosquitto's own Windows service), 1884 is used.

Passwords are written as ``user:password`` lines and hashed in place with
``mosquitto_passwd -U``, so they never appear on a command line.
"""
import os
import shlex
import socket
import subprocess
import tempfile
from pathlib import Path

from installer.steps import SERVER_DIR, server_import_path, system

SERVER_USER = "greenhouse-server"
LOCAL_DIR = SERVER_DIR / "data" / "mosquitto"
LINUX_CONF = "/etc/mosquitto/conf.d/greenhouse.conf"
LINUX_PASSWD = "/etc/mosquitto/greenhouse.passwd"
LINUX_ACL = "/etc/mosquitto/greenhouse.acl"
PORTS = (1883, 1884)


def acl_text(device_ids: list[int], prefix: str = "greenhouse") -> str:
    """
    Topic permissions: the server reads and writes everything, each
    controller only its own topics (same rules as ``deploy/mosquitto``).

    Args:
        device_ids (list[int]): Controllers to allow.
        prefix (str): Topic prefix.

    Returns:
        str: ACL file contents.
    """
    server_import_path()
    from scripts.add_device import ACL_TEMPLATE

    blocks = [f"# Written by the greenhouse installer.\nuser {SERVER_USER}\ntopic readwrite {prefix}/#"]
    blocks += [ACL_TEMPLATE.format(id=device_id, prefix=prefix) for device_id in device_ids]
    return "\n\n".join(blocks) + "\n"


def conf_text(port: int, passwd: str, acl: str, persistence_dir: str | None = None) -> str:
    """
    Broker settings.

    Args:
        port (int): Listening port.
        passwd (str): Password file path.
        acl (str): ACL file path.
        persistence_dir (str | None): Where to keep retained messages (local
            broker only; the Linux package already sets one).

    Returns:
        str: ``mosquitto.conf`` contents.
    """
    lines = ["# Written by the greenhouse installer.", f"listener {port}", "allow_anonymous false",
             f"password_file {passwd}", f"acl_file {acl}", "persistence true"]
    if persistence_dir:
        lines.append(f"persistence_location {persistence_dir.rstrip('/')}/")
    return "\n".join(lines) + "\n"


def passwd_text(logins: dict[str, str]) -> str:
    """Plain ``user:password`` lines, hashed later with ``mosquitto_passwd -U``."""
    return "".join(f"{user}:{password}\n" for user, password in logins.items())


def port_free(port: int, host: str = "0.0.0.0") -> bool:
    """
    Tell whether a TCP port can be listened on.

    Args:
        port (int): Port.
        host (str): Address.

    Returns:
        bool: True if nothing else is using it.
    """
    probe = socket.socket()
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def choose_port(is_free=port_free) -> int:
    """The first free port of ``PORTS`` (1883 unless something already uses it)."""
    for port in PORTS:
        if is_free(port):
            return port
    return PORTS[-1]


def install_command(os_name: str | None = None) -> list[str] | None:
    """
    Command that installs Mosquitto on Windows or macOS.

    Returns:
        list[str] | None: ``winget`` or ``brew`` command; None on Linux (the
        setup script installs it).
    """
    os_name = os_name or system()
    if os_name == "windows":
        return ["winget", "install", "-e", "--id", "EclipseFoundation.Mosquitto",
                "--accept-source-agreements", "--accept-package-agreements"]
    if os_name == "macos":
        return ["brew", "install", "mosquitto"]
    return None


def linux_script(staging: Path, install: bool = True) -> str:
    """
    Shell script (run as root) that sets up the system broker from staged files.

    Args:
        staging (Path): Folder holding ``greenhouse.conf``, ``greenhouse.acl``
            and the plain ``greenhouse.passwd``.
        install (bool): Install the Mosquitto package first.

    Returns:
        str: Script text.
    """
    q = lambda name: shlex.quote(str(staging / name))  # noqa: E731
    lines = ["#!/bin/sh", "set -e"]
    if install:
        lines += ["export DEBIAN_FRONTEND=noninteractive", "apt-get update",
                  "apt-get install -y mosquitto mosquitto-clients"]
    lines += [
        f"mosquitto_passwd -U {q('greenhouse.passwd')}",
        f"install -D -m 644 {q('greenhouse.conf')} {LINUX_CONF}",
        f"install -o mosquitto -g mosquitto -m 600 {q('greenhouse.acl')} {LINUX_ACL}",
        f"install -o mosquitto -g mosquitto -m 600 {q('greenhouse.passwd')} {LINUX_PASSWD}",
        "systemctl enable mosquitto",
        "systemctl restart mosquitto",
    ]
    return "\n".join(lines) + "\n"


def stage_linux(logins: dict[str, str], device_ids: list[int], port: int = 1883, prefix: str = "greenhouse",
                folder: Path | None = None) -> Path:
    """
    Write the Linux broker files and script to a private temporary folder.

    Args:
        logins (dict[str, str]): Broker users and passwords.
        device_ids (list[int]): Controllers.
        port (int): Listening port.
        prefix (str): Topic prefix.
        folder (Path | None): Where to write (default: a new temp folder).

    Returns:
        Path: The script ``setup-broker.sh`` (run it with ``pkexec sh``).
    """
    folder = folder or Path(tempfile.mkdtemp(prefix="greenhouse-broker-"))
    os.chmod(folder, 0o700)
    (folder / "greenhouse.conf").write_text(conf_text(port, LINUX_PASSWD, LINUX_ACL), encoding="utf-8")
    (folder / "greenhouse.acl").write_text(acl_text(device_ids, prefix), encoding="utf-8")
    secret = folder / "greenhouse.passwd"
    secret.write_text(passwd_text(logins), encoding="utf-8")
    os.chmod(secret, 0o600)
    script = folder / "setup-broker.sh"
    script.write_text(linux_script(folder), encoding="utf-8", newline="\n")
    return script


def write_local(logins: dict[str, str], device_ids: list[int], port: int, prefix: str = "greenhouse",
                folder: Path = LOCAL_DIR, run=subprocess.run, find=None) -> Path:
    """
    Set up the broker that ``run_all.py`` runs (Windows and macOS).

    Args:
        logins (dict[str, str]): Broker users and passwords.
        device_ids (list[int]): Controllers.
        port (int): Listening port.
        prefix (str): Topic prefix.
        folder (Path): Settings folder.
        run (callable): ``subprocess.run`` (injected in tests).
        find (callable | None): Finds ``mosquitto_passwd`` (default ``run_all.find_mosquitto``).

    Returns:
        Path: The ``mosquitto.conf`` written.

    Raises:
        RuntimeError: If ``mosquitto_passwd`` is missing or fails.
    """
    if find is None:
        server_import_path()
        from run_all import find_mosquitto as find
    tool = find("mosquitto_passwd")
    if tool is None:
        raise RuntimeError("Mosquitto is not installed (mosquitto_passwd not found).")
    folder.mkdir(parents=True, exist_ok=True)
    passwd, acl, conf = folder / "passwd", folder / "acl", folder / "mosquitto.conf"
    passwd.write_text(passwd_text(logins), encoding="utf-8")
    os.chmod(passwd, 0o600)
    result = run([tool, "-U", str(passwd)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"mosquitto_passwd failed: {result.stderr.strip() or result.stdout.strip()}")
    acl.write_text(acl_text(device_ids, prefix), encoding="utf-8")
    conf.write_text(conf_text(port, passwd.as_posix(), acl.as_posix(), folder.as_posix()), encoding="utf-8")
    return conf


def check_login(host: str, port: int, user: str | None, password: str | None, timeout: float = 10.0,
                client_factory=None, tls: bool = False) -> tuple[bool, str]:
    """
    Try to log in to a broker.

    Args:
        host (str): Broker address.
        port (int): Port.
        user (str | None): Login name.
        password (str | None): Password.
        timeout (float): Seconds to wait.
        client_factory (callable | None): Builds a paho client (injected in tests).
        tls (bool): Encrypted connection, checked against this computer's trusted roots.

    Returns:
        tuple[bool, str]: Success and a message for the user.
    """
    import ssl
    import threading

    if client_factory is None:
        from paho.mqtt.client import CallbackAPIVersion, Client

        client_factory = lambda: Client(CallbackAPIVersion.VERSION2, client_id="greenhouse-installer")  # noqa: E731
    client = client_factory()
    if user:
        client.username_pw_set(user, password)
    if tls:
        client.tls_set()
    done = threading.Event()
    outcome = {}

    def on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        outcome["code"] = reason_code
        done.set()

    client.on_connect = on_connect
    try:
        client.connect(host, port, keepalive=10)
    except ssl.SSLCertVerificationError as err:
        return False, f"The broker at {host}:{port} has a certificate this computer doesn't trust ({err.verify_message})."
    except OSError as err:
        return False, f"Can't reach the broker at {host}:{port} ({err})."
    client.loop_start()
    try:
        if not done.wait(timeout):
            return False, f"The broker at {host}:{port} didn't answer."
    finally:
        client.loop_stop()
        client.disconnect()
    code = outcome["code"]
    failed = getattr(code, "is_failure", bool(code))
    if failed:
        return False, f"The broker refused the login ({code})."
    return True, f"Logged in to the broker at {host}:{port}" + (" (encrypted)." if tls else ".")


def controller_root(host: str, port: int) -> str | None:
    """
    Which of the controller's root certificates an encrypted broker needs.

    Args:
        host (str): Broker address.
        port (int): Its TLS port.

    Returns:
        str | None: The root's name, or None if none fits or the broker
        can't be reached (the controller then tries them all itself).
    """
    server_import_path()
    from core import broker_tls

    try:
        return broker_tls.find_root(host, port)
    except OSError:
        return None
