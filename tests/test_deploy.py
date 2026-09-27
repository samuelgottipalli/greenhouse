"""Tests for deploy/: systemd unit templates and their installer (S-14)."""
import configparser
import importlib.util
import shlex

import pytest

from support import REPO_ROOT, SERVER_DIR

spec = importlib.util.spec_from_file_location("install_services", REPO_ROOT / "deploy" / "install_services.py")
install_services = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install_services)


def parse_unit(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(text)
    return parser


@pytest.fixture
def installed(tmp_path):
    install_services.install(tmp_path, user="pi", python="/opt/gh/venv/bin/python", server_dir=SERVER_DIR)
    return {p.stem: parse_unit(p.read_text()) for p in tmp_path.glob("*.service")}


def test_all_units_rendered(installed):
    assert set(installed) == set(install_services.UNITS)


@pytest.mark.parametrize("unit", install_services.UNITS)
def test_units_restart_and_run_from_server(installed, unit):
    service = installed[unit]["Service"]
    assert service["Restart"] == "always"
    assert service["User"] == "pi"
    assert service["WorkingDirectory"] == SERVER_DIR.as_posix()
    assert service["ExecStart"].startswith("/opt/gh/venv/bin/python -m ")
    assert "@" not in "".join(service.values())
    assert installed[unit]["Install"]["WantedBy"] == "multi-user.target"


@pytest.mark.parametrize("unit", ["greenhouse-ingest", "greenhouse-automation", "greenhouse-weather"])
def test_service_modules_exist(installed, unit):
    module = shlex.split(installed[unit]["Service"]["ExecStart"])[2]
    assert (SERVER_DIR / (module.replace(".", "/") + ".py")).exists()


def test_web_unit_runs_the_app(installed):
    args = shlex.split(installed["greenhouse-web"]["Service"]["ExecStart"])
    assert args[1:5] == ["-m", "streamlit", "run", "app.py"]
    assert (SERVER_DIR / "app.py").exists()


def test_rendered_files_use_lf(tmp_path):
    for path in install_services.install(tmp_path, "pi", "/usr/bin/python3"):
        assert b"\r\n" not in path.read_bytes()


def test_main_without_enable_prints_next_step(tmp_path, capsys):
    assert install_services.main(["--dest", str(tmp_path), "--user", "pi"]) == 0
    assert "systemctl enable --now greenhouse-ingest" in capsys.readouterr().out


@pytest.mark.parametrize("unit", ["greenhouse-ingest", "greenhouse-automation", "greenhouse-weather"])
def test_background_services_have_watchdog(installed, unit):
    from core.health import STALE_AFTER_S

    service = installed[unit]["Service"]
    assert int(service["WatchdogSec"]) <= STALE_AFTER_S
    assert service["NotifyAccess"] == "main"


def test_web_has_no_watchdog(installed):
    # Streamlit does not ping the watchdog, so it must not be killed for silence.
    assert "WatchdogSec" not in installed["greenhouse-web"]["Service"]
