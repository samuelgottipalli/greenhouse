"""Tests for installer/steps.py: settings file, commands, location lookup, autostart."""
import json
import os
import plistlib
import sys

import pytest

from installer import steps


def test_update_env_starts_from_the_template(env_files):
    steps.update_env({"TIMEZONE": "Europe/Paris", "NEW_KEY": "1"})
    text = env_files.read_text(encoding="utf-8")
    assert "# Copy to .env and fill in." in text  # comments kept
    assert "TIMEZONE=Europe/Paris" in text and "TIMEZONE=America/Los_Angeles" not in text
    assert text.rstrip().endswith("NEW_KEY=1")
    if os.name == "posix":
        assert env_files.stat().st_mode & 0o777 == 0o600


def test_update_env_keeps_other_values(env_files):
    env_files.write_text("# mine\nA=1\nB=2\n", encoding="utf-8")
    steps.update_env({"B": "3"})
    assert env_files.read_text(encoding="utf-8") == "# mine\nA=1\nB=3\n"
    assert steps.read_env() == {"A": "1", "B": "3"}


def test_read_env_missing_file(env_files):
    assert steps.read_env() == {}


def test_password_rules_and_hash():
    assert "8 characters" in steps.password_problem("short", "short")
    assert "don't match" in steps.password_problem("long enough", "long enougH")
    assert steps.password_problem("long enough", "long enough") is None
    from core.auth import verify_password

    assert verify_password("long enough", steps.password_hash("long enough"))


def test_geocode():
    body = {"results": [{"name": "Reno", "admin1": "Nevada", "country": "United States",
                         "latitude": 39.52963, "longitude": -119.8138, "timezone": "America/Los_Angeles"},
                        {"name": "Reno", "country": "Italy", "latitude": 45.0, "longitude": 9.0}]}
    urls = []

    def fetch(url):
        urls.append(url)
        return json.dumps(body).encode()

    places = steps.geocode("Reno", fetch)
    assert "name=Reno" in urls[0]
    assert places[0] == {"label": "Reno, Nevada, United States", "latitude": 39.5296,
                         "longitude": -119.8138, "timezone": "America/Los_Angeles"}
    assert places[1]["timezone"] == "UTC"


def test_geocode_offline_or_nothing():
    def offline(url):
        raise OSError("no network")

    assert steps.geocode("Reno", offline) == []
    assert steps.geocode("Nowhere", lambda url: b"{}") == []


def test_commands():
    assert steps.pip_install_command("py")[-2:] == ["-r", str(steps.REQUIREMENTS)]
    assert steps.upgrade_db_command("py") == ["py", "-m", "scripts.upgrade_db"]
    pull, packages, database = steps.update_commands("py")
    assert pull == (["git", "pull", "--ff-only"], steps.REPO_DIR)
    assert packages[0][0] == "py" and database[1] == steps.SERVER_DIR
    command = steps.systemd_install_command("pi", "/home/pi/greenhouse/venv/bin/python")
    assert command[0] == "pkexec" and command[-5:] == ["--user", "pi", "--python",
                                                      "/home/pi/greenhouse/venv/bin/python", "--enable"]
    assert command[2].endswith("install_services.py")


def test_run_streams_output():
    lines = []
    code = steps.run([sys.executable, "-c", "print('one'); print('two')"], on_line=lines.append)
    assert code == 0 and lines == ["one", "two"]


def test_windows_autostart(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    python = tmp_path / "venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("")
    (python.parent / "pythonw.exe").write_text("")
    path = steps.install_autostart("windows", tmp_path, str(python))
    assert path.parent.name == "Startup" and path.name == "Greenhouse Server.cmd"
    text = path.read_text(encoding="utf-8")
    assert "pythonw.exe" in text and "run_all.py" in text and b"\r\n" in path.read_bytes()


def test_macos_autostart(tmp_path):
    path = steps.install_autostart("macos", tmp_path, "/venv/bin/python")
    assert path == tmp_path / "Library" / "LaunchAgents" / "com.greenhouse.server.plist"
    agent = plistlib.loads(path.read_bytes())
    assert agent["ProgramArguments"] == ["/venv/bin/python", str(steps.SERVER_DIR / "run_all.py")]
    assert agent["RunAtLoad"] and agent["KeepAlive"]


@pytest.mark.parametrize("os_name", ["windows", "macos", "linux"])
def test_start_server(os_name, monkeypatch):
    calls = []
    if os_name == "windows" and not hasattr(steps.subprocess, "DETACHED_PROCESS"):
        monkeypatch.setattr(steps.subprocess, "DETACHED_PROCESS", 8, raising=False)
        monkeypatch.setattr(steps.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    steps.start_server(os_name, "python", popen=lambda command, **kw: calls.append((command, kw)))
    (command, kwargs), = calls
    assert kwargs["cwd"] == steps.SERVER_DIR
    if os_name == "macos":
        assert command[:3] == ["launchctl", "load", "-w"]
    else:
        assert command[-1].endswith("run_all.py")
        assert ("creationflags" in kwargs) == (os_name == "windows")


def test_dashboard_url():
    assert steps.dashboard_url("192.168.1.20") == "http://192.168.1.20:8501"
    assert steps.dashboard_url(None) == "http://localhost:8501"
