"""
Restarting things from the dashboard (Settings › System): the controller,
the dashboard and background services, and the server computer itself.

* **Controller**: an ``{"action": "restart"}`` command on its command topic
  (``core/mqtt.py``); controllers from 1.3.0 understand it.
* **Services**: under systemd (the Pi) ``systemctl restart --no-block`` of
  every greenhouse service, the dashboard last; ``--no-block`` queues the
  restart so the dashboard can answer before it is itself restarted. Under
  ``run_all.py`` (Windows, macOS) a request file that the supervisor picks up.
* **Computer**: ``systemctl reboot`` on Linux, ``shutdown /r`` on Windows,
  ``shutdown -r now`` on macOS.

The service account may only run exactly these commands as administrator
(``sudo -n``, no password): ``deploy/install_services.py`` writes that rule
(``SUDOERS_FILE``). Without it the buttons say what to set up.
"""
import os
import platform
import shutil
import subprocess
from pathlib import Path

from core import settings

SERVICES: tuple[str, ...] = ("greenhouse-ingest", "greenhouse-automation", "greenhouse-weather",
                             "greenhouse-firmware", "greenhouse-web")  # the dashboard last
RESTART_REQUEST: Path = settings.SERVER_DIR / "data" / "restart-request"
SUPERVISOR_ENV = "GREENHOUSE_SUPERVISOR"  # set by run_all.py for the programs it runs
SUDOERS_FILE = "/etc/sudoers.d/greenhouse-dashboard"
TIMEOUT_S = 20


def manager() -> str:
    """
    What keeps the server's programs running.

    Returns:
        str: ``"systemd"`` (a Linux service; systemd sets ``INVOCATION_ID``),
        ``"run_all"`` (``run_all.py`` on Windows or macOS) or ``"none"`` (run by hand).
    """
    if os.environ.get("INVOCATION_ID") and platform.system() == "Linux":
        return "systemd"
    if os.environ.get(SUPERVISOR_ENV) == "run_all":
        return "run_all"
    return "none"


def systemctl() -> str:
    """The full path of ``systemctl`` (sudo rules name commands by full path)."""
    return shutil.which("systemctl") or "/usr/bin/systemctl"


def restart_services_command() -> list[str]:
    """The exact command that restarts every greenhouse service (see ``sudoers_rule``)."""
    return ["sudo", "-n", systemctl(), "restart", "--no-block", *SERVICES]


def reboot_command(system: str | None = None) -> list[str]:
    """The command that restarts this computer."""
    system = system or platform.system()
    if system == "Windows":
        return ["shutdown", "/r", "/t", "5", "/c", "Greenhouse dashboard: restart requested"]
    if system == "Darwin":
        return ["sudo", "-n", "/sbin/shutdown", "-r", "now"]
    return ["sudo", "-n", systemctl(), "reboot"]


def sudoers_rule(user: str, systemctl_path: str | None = None) -> str:
    """
    The sudo rule that lets the dashboard's account run exactly the restart and
    reboot commands, and nothing else, without a password.

    Args:
        user (str): The account the services run as.
        systemctl_path (str | None): Full path of systemctl.

    Returns:
        str: Contents for ``SUDOERS_FILE``.
    """
    path = systemctl_path or systemctl()
    return (
        "# Written by deploy/install_services.py: lets the greenhouse dashboard restart its own\n"
        "# services and this computer (Settings > System). Nothing else.\n"
        f"{user} ALL=(root) NOPASSWD: {path} restart --no-block {' '.join(SERVICES)}, {path} reboot\n"
    )


def _run(command: list[str], run=subprocess.run) -> tuple[bool, str]:
    """Run a command; (success, its error output)."""
    try:
        result = run(command, capture_output=True, text=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as err:
        return False, str(err)
    return result.returncode == 0, (result.stderr or result.stdout or "").strip()


def restart_services(run=subprocess.run, kind: str | None = None) -> tuple[bool, str]:
    """
    Restart the dashboard and all background services.

    Args:
        run (callable): ``subprocess.run`` (injected in tests).
        kind (str | None): ``manager()`` (injected in tests).

    Returns:
        tuple[bool, str]: Success, and a message for the dashboard.
    """
    kind = kind or manager()
    if kind == "systemd":
        ok, error = _run(restart_services_command(), run)
        if ok:
            return True, "Restarting the background services and the dashboard."
        if "password" in error.lower() or "not allowed" in error.lower():
            return False, ("This computer doesn't allow the dashboard to restart services yet. On the server run "
                           "`sudo venv/bin/python deploy/install_services.py --user <you> --enable` once.")
        return False, f"The restart didn't start: {error or 'unknown error'}"
    if kind == "run_all":
        try:
            RESTART_REQUEST.parent.mkdir(parents=True, exist_ok=True)
            RESTART_REQUEST.write_text("restart\n", encoding="utf-8")
        except OSError as err:
            return False, f"The restart couldn't be requested: {err}"
        return True, "Restarting the background services and the dashboard."
    return False, ("The dashboard was started by hand, so nothing is there to restart it. Stop it and "
                   "start it again (or run it with run_all.py or as a service).")


def reboot(run=subprocess.run, system: str | None = None) -> tuple[bool, str]:
    """
    Restart this computer.

    Args:
        run (callable): ``subprocess.run`` (injected in tests).
        system (str | None): ``platform.system()`` (injected in tests).

    Returns:
        tuple[bool, str]: Success, and a message for the dashboard.
    """
    ok, error = _run(reboot_command(system), run)
    if ok:
        return True, "The server is restarting. The dashboard is back in a minute or two."
    if "password" in error.lower() or "not allowed" in error.lower():
        return False, ("This computer doesn't allow the dashboard to restart it yet. On the server run "
                       "`sudo venv/bin/python deploy/install_services.py --user <you> --enable` once.")
    return False, f"The restart didn't start: {error or 'unknown error'}"


def take_restart_request() -> bool:
    """For ``run_all.py``: was a restart asked for? (Removes the request.)"""
    try:
        RESTART_REQUEST.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True
