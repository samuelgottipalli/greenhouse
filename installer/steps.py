"""
Server setup steps used by the installer wizard (no GUI code here).

Each step is a plain function or a command list, so the wizard can run it
and the tests can check it without a desktop:

* packages: install ``server/requirements.txt`` into this Python;
* settings: write ``server/.env`` from ``.env.example``, keeping comments;
* location: look a town up with Open-Meteo's free geocoding API;
* database and dashboard password;
* services: systemd on Linux, or start at log-in (Windows Startup folder,
  macOS LaunchAgent) running ``server/run_all.py``;
* update: ``git pull`` plus the package and database steps again.
"""
import json
import os
import platform
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = REPO_DIR / "server"
ENV_FILE = SERVER_DIR / ".env"
ENV_EXAMPLE = SERVER_DIR / ".env.example"
REQUIREMENTS = SERVER_DIR / "requirements.txt"
DASHBOARD_PORT = 8501
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
MIN_PASSWORD = 8
AUTOSTART_NAME = "Greenhouse Server"
LAUNCH_AGENT = "com.greenhouse.server"


def system() -> str:
    """
    Name this operating system.

    Returns:
        str: ``"windows"``, ``"macos"`` or ``"linux"``.
    """
    name = platform.system()
    return {"Windows": "windows", "Darwin": "macos"}.get(name, "linux")


def server_version() -> str:
    """
    The server's version, e.g. ``1.1.0``, read from ``server/version.py``
    (read, not imported: it works before the server's packages are installed).

    Returns:
        str: The version, or ``"unknown"`` if the file is missing.
    """
    import re

    try:
        text = (SERVER_DIR / "version.py").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    found = re.search(r'^VERSION = "([^"]+)"$', text, re.M)
    return found.group(1) if found else "unknown"


def server_import_path() -> None:
    """Let this process import the server's modules (``core``, ``scripts``)."""
    if str(SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(SERVER_DIR))


# --- commands ------------------------------------------------------------------


def pip_install_command(python: str = sys.executable) -> list[str]:
    """
    Command that installs the server's packages.

    Args:
        python (str): Interpreter to install into (the project's venv).

    Returns:
        list[str]: Command line.
    """
    return [python, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(REQUIREMENTS)]


def upgrade_db_command(python: str = sys.executable) -> list[str]:
    """Command that creates or upgrades the database (run in ``server/``)."""
    return [python, "-m", "scripts.upgrade_db"]


def set_location_command(latitude: float, longitude: float, name: str = "", zone: str = "",
                         python: str = sys.executable) -> list[str]:
    """
    Command that stores the greenhouse's location in the database (run in ``server/``).

    The dashboard's Settings › Location stores it there too, and that copy
    wins over ``LATITUDE``/``LONGITUDE`` in ``.env``; so running the installer
    again changes it as expected.
    """
    command = [python, "-m", "scripts.set_location", "--latitude", f"{latitude:.4f}",
               "--longitude", f"{longitude:.4f}"]
    if name:
        command += ["--name", name]
    if zone:
        command += ["--timezone", zone]
    return command


def update_commands(python: str = sys.executable) -> list[tuple[list[str], Path]]:
    """
    Commands that update this installation to the newest version.

    Returns:
        list[tuple[list[str], Path]]: ``(command, working folder)`` in order:
        pull the code, install packages, upgrade the database.
    """
    return [
        (["git", "pull", "--ff-only"], REPO_DIR),
        (pip_install_command(python), REPO_DIR),
        (upgrade_db_command(python), SERVER_DIR),
    ]


def is_git_checkout() -> bool:
    """bool: True if this copy came from ``git clone`` (so it can update itself)."""
    return (REPO_DIR / ".git").exists()


def run(command: list[str], cwd: Path = REPO_DIR, on_line=None) -> int:
    """
    Run a command, passing each line of its output to ``on_line``.

    Args:
        command (list[str]): Command line.
        cwd (Path): Working folder.
        on_line (callable | None): Called with each output line.

    Returns:
        int: Exit code.
    """
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace")
    for line in process.stdout:
        if on_line:
            on_line(line.rstrip("\n"))
    return process.wait()


# --- settings file ---------------------------------------------------------------


def read_env(path: Path | None = None) -> dict[str, str]:
    """
    Read ``KEY=value`` lines.

    Args:
        path (Path | None): Env file (default ``ENV_FILE``).

    Returns:
        dict[str, str]: Values (empty if the file doesn't exist).
    """
    path = path or ENV_FILE
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def update_env(values: dict[str, str], path: Path | None = None, template: Path | None = None) -> None:
    """
    Set values in ``server/.env``, creating it from the template if needed.

    Existing lines keep their place and comments; new keys are added at the end.
    The file is made readable by its owner only (it holds passwords).

    Args:
        values (dict[str, str]): Keys and values to set.
        path (Path | None): Env file (default ``ENV_FILE``).
        template (Path | None): Starting point when the file doesn't exist
            (default ``ENV_EXAMPLE``).
    """
    path, template = path or ENV_FILE, template or ENV_EXAMPLE
    lines = (path if path.exists() else template).read_text(encoding="utf-8").splitlines()
    remaining = dict(values)
    for index, line in enumerate(lines):
        key = line.partition("=")[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in remaining:
            lines[index] = f"{key}={remaining.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def password_problem(password: str, again: str) -> str | None:
    """
    Check a new dashboard password.

    Returns:
        str | None: What's wrong, or None if it is fine.
    """
    if len(password) < MIN_PASSWORD:
        return f"Use at least {MIN_PASSWORD} characters."
    if password != again:
        return "The two passwords don't match."
    return None


def password_hash(password: str) -> str:
    """Hash a dashboard password the way the server checks it (``core.auth``)."""
    server_import_path()
    from core.auth import hash_password

    return hash_password(password)


# --- location ----------------------------------------------------------------


def geocode(name: str, fetch=None) -> list[dict]:
    """
    Find places by name (Open-Meteo geocoding, no account needed).

    Args:
        name (str): Town or city, e.g. ``"Reno"``.
        fetch (callable | None): ``fetch(url) -> bytes`` (injected in tests).

    Returns:
        list[dict]: Up to 8 places with ``label``, ``latitude``,
        ``longitude`` and ``timezone``; empty if none or offline.
    """
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=10).read())
    url = GEOCODE_URL + "?" + urllib.parse.urlencode({"name": name, "count": 8, "language": "en"})
    try:
        data = json.loads(fetch(url))
    except (OSError, ValueError):
        return []
    places = []
    for item in data.get("results") or []:
        parts = [item.get("name"), item.get("admin1"), item.get("country")]
        places.append({
            "label": ", ".join(p for p in parts if p),
            "latitude": round(float(item["latitude"]), 4),
            "longitude": round(float(item["longitude"]), 4),
            "timezone": item.get("timezone") or "UTC",
        })
    return places


# --- services --------------------------------------------------------------------


def systemd_install_command(user: str, python: str = sys.executable) -> list[str]:
    """
    Command that installs and starts the systemd services (asks for the
    administrator password through ``pkexec``).

    Args:
        user (str): Account the services run as.
        python (str): The project's interpreter.

    Returns:
        list[str]: Command line.
    """
    return ["pkexec", python, str(REPO_DIR / "deploy" / "install_services.py"), "--user", user,
            "--python", python, "--enable"]


def background_python(python: str = sys.executable) -> str:
    """
    The interpreter to run the server with, without a console window.

    Returns:
        str: ``pythonw.exe`` next to ``python.exe`` on Windows, else ``python``.
    """
    path = Path(python)
    windowless = path.with_name("pythonw.exe")
    return str(windowless) if path.name.lower() == "python.exe" and windowless.exists() else python


def windows_startup_script(python: str = sys.executable) -> str:
    """
    Contents of the Startup-folder script that starts the server at log-in.

    Returns:
        str: A ``.cmd`` file.
    """
    return ("@echo off\r\n"
            f'cd /d "{SERVER_DIR}"\r\n'
            f'start "" "{background_python(python)}" "{SERVER_DIR / "run_all.py"}"\r\n')


def macos_launch_agent(python: str = sys.executable) -> str:
    """
    Contents of the LaunchAgent that starts the server at log-in and keeps it running.

    Returns:
        str: A property list.
    """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LAUNCH_AGENT}</string>
  <key>ProgramArguments</key>
  <array><string>{python}</string><string>{SERVER_DIR / "run_all.py"}</string></array>
  <key>WorkingDirectory</key><string>{SERVER_DIR}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""


def autostart_path(os_name: str | None = None, home: Path | None = None) -> Path:
    """
    Where the log-in start file goes.

    Args:
        os_name (str | None): ``"windows"`` or ``"macos"`` (default: this system).
        home (Path | None): Home folder (default: the user's).

    Returns:
        Path: The file to write.
    """
    os_name = os_name or system()
    home = home or Path.home()
    if os_name == "windows":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{AUTOSTART_NAME}.cmd"
    return home / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT}.plist"


def install_autostart(os_name: str | None = None, home: Path | None = None,
                      python: str = sys.executable) -> Path:
    """
    Make the server start when this user logs in (Windows or macOS).

    Args:
        os_name (str | None): ``"windows"`` or ``"macos"``.
        home (Path | None): Home folder.
        python (str): The project's interpreter.

    Returns:
        Path: The file written.
    """
    os_name = os_name or system()
    path = autostart_path(os_name, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if os_name == "windows":
        path.write_text(windows_startup_script(python), encoding="utf-8", newline="")
    else:
        path.write_text(macos_launch_agent(python), encoding="utf-8")
    return path


def start_server_command(os_name: str | None = None, python: str = sys.executable) -> list[str]:
    """
    Command that starts the server now, in the background.

    Returns:
        list[str]: ``launchctl load`` of the agent on macOS, else ``run_all.py``.
    """
    os_name = os_name or system()
    if os_name == "macos":
        return ["launchctl", "load", "-w", str(autostart_path("macos"))]
    return [background_python(python), str(SERVER_DIR / "run_all.py")]


def start_server(os_name: str | None = None, python: str = sys.executable, popen=subprocess.Popen):
    """Start the server in the background, detached from the installer."""
    os_name = os_name or system()
    command = start_server_command(os_name, python)
    if os_name == "windows":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        return popen(command, cwd=SERVER_DIR, creationflags=flags, close_fds=True)
    return popen(command, cwd=SERVER_DIR, start_new_session=True)


def dashboard_url(host: str | None) -> str:
    """The dashboard's address as other devices on the network reach it."""
    return f"http://{host or 'localhost'}:{DASHBOARD_PORT}"
