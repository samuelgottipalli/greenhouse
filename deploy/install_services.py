"""
Install the greenhouse services as systemd units (Linux, e.g. Raspberry Pi OS).

Usage (as root, from anywhere in the repository)::

    sudo venv/bin/python deploy/install_services.py --user pi --enable

Renders ``deploy/systemd/*.service`` and ``*.timer`` with this checkout's ``server/`` folder,
the Python interpreter running this script (use the project venv) and the
given user, writes them to ``/etc/systemd/system`` (or ``--dest``), and with
``--enable`` reloads systemd and starts them. Every long-running unit restarts
5 s after a crash (``Restart=always``); ``greenhouse-retention.timer`` runs the
retention job nightly at 03:30. Logs go to the journal::

    journalctl -u greenhouse-ingest -f
"""
import argparse
import getpass
import subprocess
import sys
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parent
REPO_DIR = DEPLOY_DIR.parent
TEMPLATE_DIR = DEPLOY_DIR / "systemd"
UNITS = ["greenhouse-ingest", "greenhouse-automation", "greenhouse-weather", "greenhouse-web"]
# Scheduled jobs: the .timer is enabled; it starts the matching one-shot .service.
TIMERS = ["greenhouse-retention", "greenhouse-alerts"]


def render(template: str, user: str, python: str, server_dir: Path) -> str:
    """
    Fill in a unit template.

    Args:
        template (str): Unit file text with ``@USER@``, ``@PYTHON@`` and
            ``@SERVER_DIR@`` placeholders.
        user (str): Account the service runs as.
        python (str): Absolute path of the Python interpreter.
        server_dir (Path): The repository's ``server/`` folder.

    Returns:
        str: The unit file text.
    """
    return (template.replace("@USER@", user)
                    .replace("@PYTHON@", python)
                    .replace("@SERVER_DIR@", server_dir.as_posix()))


def install(dest: Path, user: str, python: str, server_dir: Path = REPO_DIR / "server") -> list[Path]:
    """
    Write all rendered units into a folder.

    Args:
        dest (Path): Target folder, normally ``/etc/systemd/system``.
        user (str): Account the services run as.
        python (str): Absolute path of the Python interpreter.
        server_dir (Path): The repository's ``server/`` folder.

    Returns:
        list[Path]: Files written.
    """
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for template in sorted(TEMPLATE_DIR.glob("greenhouse-*.*")):
        target = dest / template.name
        target.write_text(render(template.read_text(encoding="utf-8"), user, python, server_dir),
                          encoding="utf-8", newline="\n")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    """
    Command-line entry point.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Install greenhouse systemd units.")
    parser.add_argument("--user", default=getpass.getuser(), help="account to run the services as")
    parser.add_argument("--python", default=sys.executable, help="interpreter (default: this one)")
    parser.add_argument("--dest", type=Path, default=Path("/etc/systemd/system"))
    parser.add_argument("--enable", action="store_true", help="reload systemd and start the services")
    args = parser.parse_args(argv)

    for path in install(args.dest, args.user, args.python):
        print(f"wrote {path}")
    if args.enable:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "enable", "--now", *UNITS, *(f"{t}.timer" for t in TIMERS)], check=True)
        print("Services enabled and started. Check them with: systemctl status 'greenhouse-*'")
    else:
        print("Now run: sudo systemctl daemon-reload && sudo systemctl enable --now "
              + " ".join(UNITS + [f"{t}.timer" for t in TIMERS]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
