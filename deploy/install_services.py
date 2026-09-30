"""
Install the greenhouse services as systemd units (Linux, e.g. Raspberry Pi OS).

Usage (as root, from anywhere in the repository)::

    sudo venv/bin/python deploy/install_services.py --user pi --enable

Renders ``deploy/systemd/*.service`` and ``*.timer`` with this checkout's ``server/`` folder,
the Python interpreter running this script (use the project venv) and the
given user, writes them to ``/etc/systemd/system`` (or ``--dest``), and with
``--enable`` reloads systemd and starts them. Every long-running unit restarts
5 s after a crash (``Restart=always``); ``greenhouse-retention.timer`` runs the
monthly job (summaries, then clean-up) on the 1st and after every start. Logs go to the journal::

    journalctl -u greenhouse-ingest -f

It also writes ``/etc/sudoers.d/greenhouse-dashboard`` (``--sudoers-dir``),
which lets the services' account run exactly two commands as administrator
without a password: restarting the greenhouse services, and restarting the
computer (the dashboard's Settings › System buttons; ``server/core/system.py``).
The file is checked with ``visudo`` before it is put in place.
"""
import argparse
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEPLOY_DIR = Path(__file__).resolve().parent
REPO_DIR = DEPLOY_DIR.parent
TEMPLATE_DIR = DEPLOY_DIR / "systemd"
UNITS = ["greenhouse-ingest", "greenhouse-automation", "greenhouse-weather", "greenhouse-firmware",
         "greenhouse-web"]
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


def install_sudoers(folder: Path, user: str, check=subprocess.run) -> Path | None:
    """
    Write the sudo rule for the dashboard's restart buttons, if ``visudo`` accepts it.

    Args:
        folder (Path): Normally ``/etc/sudoers.d``.
        user (str): The services' account.
        check (callable): Runs ``visudo -cf`` (injected in tests).

    Returns:
        Path | None: The file written, or None if it was rejected (nothing changed).
    """
    sys.path.insert(0, str(REPO_DIR / "server"))
    from core import system

    folder.mkdir(parents=True, exist_ok=True)
    target = folder / Path(system.SUDOERS_FILE).name
    staged = folder / (target.name + ".new")  # sudo ignores names containing a dot
    staged.write_text(system.sudoers_rule(user), encoding="utf-8", newline="\n")
    os.chmod(staged, 0o440)
    visudo = shutil.which("visudo")
    if visudo and check([visudo, "-cf", str(staged)], capture_output=True).returncode != 0:
        os.chmod(staged, 0o600)  # read-only files can't be removed on Windows (tests)
        staged.unlink()
        return None
    os.replace(staged, target)
    return target


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
    parser.add_argument("--sudoers-dir", type=Path, default=None,
                        help="where the rule for the dashboard's restart buttons goes "
                             "(default with --enable: /etc/sudoers.d)")
    args = parser.parse_args(argv)

    for path in install(args.dest, args.user, args.python):
        print(f"wrote {path}")
    sudoers_dir = args.sudoers_dir or (Path("/etc/sudoers.d") if args.enable else None)
    if sudoers_dir is not None:
        try:
            rule = install_sudoers(sudoers_dir, args.user)
        except OSError as err:  # not run as root: the restart buttons will say what to do
            print(f"Skipped the restart-button permission ({err})")
        else:
            print(f"wrote {rule}" if rule else "The restart-button permission was rejected by visudo; skipped")
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
