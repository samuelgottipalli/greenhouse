"""
Tests for the installer window (installer/wizard.py), run offscreen.

Page logic is driven directly; background work runs synchronously through a
replaced ``run_task`` (one test checks the real threaded runner).
"""
import os
import time
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication  # noqa: E402

from installer import broker, pico, steps, wizard  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch, env_files, tmp_path):
    from core import device_credentials

    monkeypatch.setattr(device_credentials, "CREDENTIALS_FILE", tmp_path / "creds.json")
    monkeypatch.setattr(pico, "current_wifi", lambda: ("Home", False))
    monkeypatch.setattr(pico, "find_bootsel", lambda: None)
    monkeypatch.setattr(pico, "find_serial_ports", lambda: [])
    w = wizard.InstallerWizard()

    def run_now(task, on_line, on_done):
        try:
            message = task(on_line)
        except Exception as err:
            on_done(False, str(err))
        else:
            on_done(True, message or "")

    w.run_task = run_now
    yield w
    w.close()


def page(window, cls):
    return next(window.page(i) for i in window.pageIds() if isinstance(window.page(i), cls))


def test_pages(window):
    assert [window.page(i).title() for i in window.pageIds()] == [
        "Welcome", "Programs", "Your greenhouse", "Messaging", "Start the server", "Controller", "All set"]


def test_update_button_follows_git(window, monkeypatch):
    assert page(window, wizard.WelcomePage).update_button.isHidden() == (not steps.is_git_checkout())


def test_update_runs_every_step(window, monkeypatch):
    ran = []
    monkeypatch.setattr(steps, "run", lambda command, cwd, log: ran.append(command[:2]) or 0)
    welcome = page(window, wizard.WelcomePage)
    welcome.update()
    assert ran[0] == ["git", "pull"] and len(ran) == 3
    assert welcome.status.text().startswith("✔")


def test_packages_page(window, monkeypatch):
    codes = [1, 0]
    monkeypatch.setattr(steps, "run", lambda command, cwd, log: log("Collecting streamlit") or codes.pop(0))
    packages = page(window, wizard.PackagesPage)
    packages.initializePage()
    assert not packages.isComplete() and "✖" in packages.status.text()
    assert "Collecting streamlit" in packages.log.toPlainText()
    packages.start()
    assert packages.isComplete() and "✔" in packages.status.text()


def test_greenhouse_page_saves_settings(window, monkeypatch, env_files):
    commands = []
    monkeypatch.setattr(steps, "run", lambda command, cwd, log: commands.append(command[2:]) or 0)
    monkeypatch.setattr(steps, "geocode", lambda name: [
        {"label": "Reno, Nevada", "latitude": 39.5296, "longitude": -119.8138, "timezone": "America/Los_Angeles"}])
    home = page(window, wizard.GreenhousePage)
    home.initializePage()
    home.town.setText("Reno")
    home.find_town()
    assert home.zone.currentText() == "America/Los_Angeles" and home.latitude.value() == pytest.approx(39.5296)
    home.password.setText("short")
    home.again.setText("short")
    assert home.validatePage() is False and "8 characters" in home.note.text()
    home.password.setText("a good password")
    home.again.setText("a good password")
    assert home.validatePage() is True
    env = steps.read_env()
    assert env["TIMEZONE"] == "America/Los_Angeles" and env["LATITUDE"] == "39.5296"
    assert env["APP_PASSWORD_HASH"].startswith("pbkdf2_sha256:")
    # The location is stored in the database too (where Settings › Location keeps it).
    assert commands[-2] == ["scripts.upgrade_db"]
    assert commands[-1] == ["scripts.set_location", "--latitude", "39.5296", "--longitude", "-119.8138",
                            "--name", "Reno, Nevada", "--timezone", "America/Los_Angeles"]
    # Running it again with an empty password keeps the old one.
    old = env["APP_PASSWORD_HASH"]
    home.password.setText("")
    home.again.setText("")
    assert home.validatePage() is True and steps.read_env()["APP_PASSWORD_HASH"] == old
    home.latitude.setValue(40.0)  # typed by hand: no place name
    assert home.validatePage() is True and "--name" not in commands[-1]


def test_greenhouse_page_rejects_unknown_zone_and_failed_database(window, monkeypatch):
    home = page(window, wizard.GreenhousePage)
    home.zone.setCurrentText("Mars/Olympus")
    assert home.validatePage() is False
    home.zone.setCurrentText("UTC")
    home.password.setText("a good password")
    home.again.setText("a good password")
    monkeypatch.setattr(steps, "run", lambda command, cwd, log: log("disk full") or 1)
    assert home.validatePage() is False and "disk full" in home.note.text()


def test_broker_page_existing_broker(window, monkeypatch):
    from core import setup_code

    monkeypatch.setattr(setup_code, "lan_address", lambda: "192.168.1.20")
    monkeypatch.setattr(broker, "check_login", lambda *a, **k: (True, "Logged in."))
    messaging = page(window, wizard.BrokerPage)
    messaging.existing.setChecked(True)
    messaging.host.setText("")
    messaging.start()
    assert "address" in messaging.status.text()
    messaging.host.setText("10.0.0.9")
    messaging.user.setText("greenhouse-server")
    messaging.secret.setText("pw")
    messaging.start()
    assert messaging.isComplete()
    env = steps.read_env()
    assert (env["MQTT_HOST"], env["MQTT_USERNAME"], env["MQTT_PASSWORD"], env["PUBLIC_HOST"]) == \
        ("10.0.0.9", "greenhouse-server", "pw", "192.168.1.20")


def test_broker_page_local_windows(window, monkeypatch, tmp_path):
    from core import device_credentials, setup_code

    import run_all

    monkeypatch.setattr(steps, "system", lambda: "windows")
    monkeypatch.setattr(setup_code, "lan_address", lambda: "192.168.1.20")
    monkeypatch.setattr(run_all, "find_mosquitto", lambda name="mosquitto": "C:/mosquitto/" + name)
    monkeypatch.setattr(broker, "choose_port", lambda: 1884)
    written = {}

    def write_local(logins, device_ids, port, **kw):
        written.update(logins=logins, device_ids=device_ids, port=port)
        return tmp_path / "mosquitto.conf"

    monkeypatch.setattr(broker, "write_local", write_local)
    started = []
    monkeypatch.setattr(wizard.subprocess, "Popen", lambda command, **kw: started.append(command) or
                        types.SimpleNamespace(terminate=lambda: started.append("stopped")))
    monkeypatch.setattr(wizard.time, "sleep", lambda s: None)
    monkeypatch.setattr(broker, "check_login", lambda host, port, user, secret: (True, "ok"))
    messaging = page(window, wizard.BrokerPage)
    messaging.start()
    assert messaging.isComplete(), messaging.status.text()
    assert written["port"] == 1884 and written["device_ids"] == [1]
    assert started[-1] == "stopped"
    login = device_credentials.get(1)
    assert written["logins"][login["user"]] == login["password"]
    env = steps.read_env()
    assert (env["MQTT_PORT"], env["MQTT_USERNAME"]) == ("1884", "greenhouse-server")
    assert written["logins"]["greenhouse-server"] == env["MQTT_PASSWORD"]


def test_controller_page_needs_a_controller(window, monkeypatch):
    controller = page(window, wizard.ControllerPage)
    controller.initializePage()
    assert controller.ssid.text() == "Home"
    assert "Nothing yet" in controller.found.text()
    controller.start()
    assert "No controller found" in controller.status.text()
    controller.cleanupPage()


def test_controller_page_warns_about_5ghz(window, monkeypatch):
    monkeypatch.setattr(pico, "current_wifi", lambda: ("Fast", True))
    controller = page(window, wizard.ControllerPage)
    controller.initializePage()
    assert "5 GHz" in controller.band_note.text()
    controller.cleanupPage()


def test_controller_page_builds_the_plan(window, monkeypatch):
    from core import device_credentials, setup_code

    monkeypatch.setattr(pico, "find_serial_ports", lambda: ["COM5"])
    monkeypatch.setattr(setup_code, "lan_address", lambda: "192.168.1.20")
    steps.update_env({"MQTT_USERNAME": "greenhouse-server", "MQTT_PASSWORD": "s", "MQTT_PORT": "1884",
                      "MQTT_HOST": "localhost", "TIMEZONE": "Europe/Paris", "PUBLIC_HOST": ""})
    controller = page(window, wizard.ControllerPage)
    controller.initializePage()
    assert "COM5" in controller.found.text()
    assert "no broker login" in controller.before()
    device_credentials.save(1, "greenhouse-device-1", "d")
    assert controller.before() is None
    assert controller.plan["answers"] == {
        "wifi_ssid": "Home", "wifi_password": "", "mqtt_broker": "192.168.1.20", "mqtt_port": 1884,
        "mqtt_user": "greenhouse-device-1", "mqtt_password": "d", "device_id": 1, "timezone": "Europe/Paris"}
    assert controller.plan["server"] == ("localhost", 1884, "greenhouse-server", "s")
    controller.cleanupPage()


PLAN = {"bootsel": None,
        "answers": {"wifi_ssid": "Home", "wifi_password": "wifi-pass", "mqtt_broker": "192.168.1.20",
                    "mqtt_port": 1883, "mqtt_user": "greenhouse-device-1", "mqtt_password": "d", "device_id": 1,
                    "timezone": "UTC"},
        "server": ("localhost", 1883, "greenhouse-server", "s")}


@pytest.fixture
def usb(monkeypatch):
    """Record the controller steps instead of touching hardware."""
    record = types.SimpleNamespace(commands=[], flashed=[], online=True)
    monkeypatch.setattr(steps, "run", lambda command, cwd, log: record.commands.append(command) or 0)
    monkeypatch.setattr(pico, "wait_online", lambda *a, **k: record.online)
    monkeypatch.setattr(pico, "latest_uf2_url", lambda board: "https://example/" + board + ".uf2")
    monkeypatch.setattr(pico, "flash_micropython", lambda drive, data: record.flashed.append((drive, data)))
    monkeypatch.setattr(wizard.urllib.request, "urlopen",
                        lambda url, timeout=0: types.SimpleNamespace(read=lambda: b"UF2"))
    return record


def test_set_up_controller_over_serial(usb):
    lines = []
    message = wizard.set_up_controller(PLAN, lines.append, wait=lambda timeout: "COM5", sleep=lambda s: None)
    assert message == "Controller 1 is online."
    reset, copy = usb.commands
    assert reset[-1] == "reset" and copy[4] == "COM5" and copy[-1] == "reset"
    assert any("config.json" in part for part in copy)
    assert usb.flashed == []


def test_set_up_new_pico_installs_micropython(usb, tmp_path):
    plan = dict(PLAN, bootsel=(tmp_path, "RPI_PICO2_W"))
    lines = []
    wizard.set_up_controller(plan, lines.append, wait=lambda timeout: "COM5", sleep=lambda s: None)
    assert usb.flashed == [(tmp_path, b"UF2")]
    assert any("RPI_PICO2_W" in line for line in lines)


def test_set_up_controller_failures(usb):
    with pytest.raises(RuntimeError, match="isn't connected"):
        wizard.set_up_controller(PLAN, print, wait=lambda timeout: None, sleep=lambda s: None)
    usb.online = False
    with pytest.raises(RuntimeError, match="setup hotspot"):
        wizard.set_up_controller(PLAN, print, wait=lambda timeout: "COM5", sleep=lambda s: None)


def test_services_page_windows(window, monkeypatch):
    monkeypatch.setattr(steps, "system", lambda: "windows")
    calls = []
    monkeypatch.setattr(steps, "install_autostart", lambda os_name: calls.append("autostart") or "Startup/x.cmd")
    monkeypatch.setattr(steps, "start_server", lambda os_name: calls.append("start"))
    monkeypatch.setattr(wizard.urllib.request, "urlopen", lambda url, timeout=0: object())
    services = page(window, wizard.ServicesPage)
    services.initializePage()
    services.start()
    assert calls == ["autostart", "start"] and services.isComplete()
    services.autostart.setChecked(False)
    calls.clear()
    services.start()
    assert calls == ["start"]


def test_services_page_linux(window, monkeypatch):
    monkeypatch.setattr(steps, "system", lambda: "linux")
    ran = []
    monkeypatch.setattr(steps, "run", lambda command, cwd, log: ran.append(command) or 0)
    monkeypatch.setattr(wizard.urllib.request, "urlopen", lambda url, timeout=0: object())
    services = page(window, wizard.ServicesPage)
    services.initializePage()
    assert services.autostart.isHidden()
    services.start()
    assert ran[0][0] == "pkexec" and services.isComplete()


def test_done_page(window, monkeypatch):
    from core import setup_code

    monkeypatch.setattr(setup_code, "lan_address", lambda: "192.168.1.20")
    done = page(window, wizard.DonePage)
    done.initializePage()
    assert "http://192.168.1.20:8501" in done.text.text()


def test_real_background_runner(app):
    w = wizard.InstallerWizard()
    results, lines = [], []
    w.run_task(lambda log: (log("working"), "finished")[1], lines.append, lambda ok, msg: results.append((ok, msg)))
    deadline = time.monotonic() + 10
    while not results and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    while w.threads and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert results == [(True, "finished")] and lines == ["working"]
    w.close()


def test_window_title_shows_the_version(window):
    from version import VERSION

    assert window.windowTitle() == f"Greenhouse setup {VERSION}"
    assert steps.server_version() == VERSION
