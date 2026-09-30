"""
Tests for restarting from the dashboard (Settings › System): core/system.py,
the controller restart message, run_all.py's restart request, the sudo rule
written by deploy/install_services.py, and the System tab.
"""
import importlib.util
import json
import subprocess
import types

import pytest

from core import db, mqtt, system
from support import REPO_ROOT, run_section


class Ran:
    """A stand-in for subprocess.run that records commands and answers as told."""

    def __init__(self, code=0, stderr=""):
        self.code, self.stderr, self.commands = code, stderr, []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        return types.SimpleNamespace(returncode=self.code, stderr=self.stderr, stdout="")


# --- core/system.py ------------------------------------------------------------------------


def test_manager(monkeypatch):
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv(system.SUPERVISOR_ENV, raising=False)
    assert system.manager() == "none"
    monkeypatch.setenv(system.SUPERVISOR_ENV, "run_all")
    assert system.manager() == "run_all"
    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setattr(system.platform, "system", lambda: "Linux")
    assert system.manager() == "systemd"


def test_restart_services_under_systemd(monkeypatch):
    monkeypatch.setattr(system, "systemctl", lambda: "/usr/bin/systemctl")
    ran = Ran()
    ok, message = system.restart_services(run=ran, kind="systemd")
    assert ok and "Restarting" in message
    assert ran.commands == [["sudo", "-n", "/usr/bin/systemctl", "restart", "--no-block", *system.SERVICES]]
    assert system.SERVICES[-1] == "greenhouse-web"  # the dashboard last


def test_restart_services_without_permission():
    ok, message = system.restart_services(run=Ran(1, "sudo: a password is required"), kind="systemd")
    assert not ok and "install_services.py" in message


def test_restart_services_under_run_all(monkeypatch, tmp_path):
    monkeypatch.setattr(system, "RESTART_REQUEST", tmp_path / "data" / "restart-request")
    ok, _ = system.restart_services(kind="run_all")
    assert ok and system.RESTART_REQUEST.exists()
    assert system.take_restart_request() is True and not system.RESTART_REQUEST.exists()
    assert system.take_restart_request() is False


def test_restart_services_started_by_hand():
    ok, message = system.restart_services(kind="none")
    assert not ok and "by hand" in message


@pytest.mark.parametrize("os_name, first", [("Linux", ["sudo", "-n", "/usr/bin/systemctl", "reboot"]),
                                            ("Windows", ["shutdown", "/r", "/t", "5"]),
                                            ("Darwin", ["sudo", "-n", "/sbin/shutdown", "-r", "now"])])
def test_reboot_commands(monkeypatch, os_name, first):
    monkeypatch.setattr(system, "systemctl", lambda: "/usr/bin/systemctl")
    ran = Ran()
    ok, _ = system.reboot(run=ran, system=os_name)
    assert ok and ran.commands[0][:len(first)] == first


def test_reboot_failures():
    assert "install_services.py" in system.reboot(run=Ran(1, "sudo: a password is required"), system="Linux")[1]

    def missing(command, **kwargs):
        raise FileNotFoundError("shutdown")

    ok, message = system.reboot(run=missing, system="Windows")
    assert not ok and "shutdown" in message


def test_sudoers_rule_allows_exactly_two_commands():
    rule = system.sudoers_rule("piserver", "/usr/bin/systemctl")
    lines = [line for line in rule.splitlines() if not line.startswith("#")]
    assert lines == ["piserver ALL=(root) NOPASSWD: /usr/bin/systemctl restart --no-block greenhouse-ingest "
                     "greenhouse-automation greenhouse-weather greenhouse-firmware greenhouse-web, "
                     "/usr/bin/systemctl reboot"]
    # The rule matches the command the dashboard runs, word for word.
    command = " ".join(system.restart_services_command()[2:]).replace(system.systemctl(), "/usr/bin/systemctl")
    assert command in lines[0]


def test_controller_restart_message(monkeypatch):
    sent = []
    monkeypatch.setattr(mqtt, "single", lambda **kw: sent.append(kw))
    assert mqtt.publish_controller_restart(3)
    assert sent[0]["topic"] == "greenhouse/3/relay/set"
    assert json.loads(sent[0]["payload"]) == {"action": "restart", "source": "web"}


# --- run_all.py -----------------------------------------------------------------------------


def test_run_all_restarts_everything_but_the_broker(tmp_path):
    import run_all

    class Process:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    children = [run_all.Child(name, [name]) for name in ("broker", "web", "ingest")]
    for child in children:
        child.process, child.started_at = Process(), 0.0
    started = []
    supervisor = run_all.Supervisor(children, [], popen=lambda command, **kw: started.append((command, kw)) or Process(),
                                    clock=lambda: 100.0, log_dir=tmp_path, restart_request=tmp_path / "restart-request")
    supervisor.step()
    assert started == []  # no request: nothing happens
    (tmp_path / "restart-request").write_text("restart")
    supervisor.step()
    assert sorted(command[0] for command, _ in started) == ["ingest", "web"]
    assert not children[0].process.terminated  # the broker kept running
    assert not (tmp_path / "restart-request").exists()
    assert all(kw["env"]["GREENHOUSE_SUPERVISOR"] == "run_all" for _, kw in started)


# --- deploy/install_services.py --------------------------------------------------------------


@pytest.fixture
def install_services():
    spec = importlib.util.spec_from_file_location("install_services", REPO_ROOT / "deploy" / "install_services.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_sudoers(install_services, tmp_path, monkeypatch):
    monkeypatch.setattr(install_services.shutil, "which", lambda name: "/usr/sbin/visudo")
    checked = []
    written = install_services.install_sudoers(tmp_path, "piserver",
                                               check=lambda cmd, **kw: checked.append(cmd) or types.SimpleNamespace(returncode=0))
    assert written == tmp_path / "greenhouse-dashboard"
    assert "piserver ALL=(root) NOPASSWD:" in written.read_text()
    assert checked[0][:2] == ["/usr/sbin/visudo", "-cf"]
    assert not list(tmp_path.glob("*.new"))


def test_install_sudoers_rejected(install_services, tmp_path, monkeypatch):
    monkeypatch.setattr(install_services.shutil, "which", lambda name: "/usr/sbin/visudo")
    assert install_services.install_sudoers(tmp_path, "pi", check=lambda cmd, **kw: types.SimpleNamespace(returncode=1)) is None
    assert list(tmp_path.iterdir()) == []


def test_main_writes_sudoers_only_when_asked(install_services, tmp_path, capsys):
    install_services.main(["--dest", str(tmp_path / "units"), "--user", "pi"])
    assert "greenhouse-dashboard" not in capsys.readouterr().out
    install_services.main(["--dest", str(tmp_path / "units"), "--user", "pi", "--sudoers-dir", str(tmp_path / "s")])
    assert (tmp_path / "s" / "greenhouse-dashboard").exists()


# --- Settings › System ----------------------------------------------------------------------


def labels(at):
    return [b.label for b in at.button]


def online(version_name):
    db.set_device_status("online", "2026-09-29 09:00:00", device_id=1)
    db.update_firmware_status(1, "abc123", "running", "", "2026-09-29 09:00:00", name=version_name)


def test_system_tab_buttons(seeded_db, monkeypatch):
    monkeypatch.setattr(system, "manager", lambda: "systemd")
    online("1.3.0")
    at = run_section("system")
    assert not at.exception, [e.message for e in at.exception]
    assert labels(at) == ["Restart the controller", "Restart the dashboard and background services",
                          "Restart the server computer"]
    assert not any(b.disabled for b in at.button)


def test_controller_button_needs_a_new_enough_online_controller(seeded_db, monkeypatch):
    online("1.1.1")
    at = run_section("system")
    button = next(b for b in at.button if b.label == "Restart the controller")
    assert button.disabled and any("1.3.0 or later" in c.value for c in at.caption)
    db.set_device_status("offline", "2026-09-29 09:05:00", device_id=1)
    at = run_section("system")
    assert any("offline" in c.value for c in at.caption)


def test_services_button_disabled_when_started_by_hand(seeded_db, monkeypatch):
    monkeypatch.setattr(system, "manager", lambda: "none")
    at = run_section("system")
    assert next(b for b in at.button if b.label.startswith("Restart the dashboard")).disabled


def test_confirm_then_restart_the_controller(seeded_db, monkeypatch):
    online("1.3.0")
    sent = []
    monkeypatch.setattr(mqtt, "publish_controller_restart", lambda device_id: sent.append(device_id) or True)
    at = run_section("system")
    next(b for b in at.button if b.label == "Restart the controller").click().run()
    assert "Restart the controller?" in at.warning[0].value and sent == []  # asks first
    next(b for b in at.button if b.label == "Yes, restart").click().run()
    assert sent == [1] and "Restart sent" in at.success[0].value


def test_cancel_does_nothing(seeded_db, monkeypatch):
    called = []
    monkeypatch.setattr(system, "reboot", lambda: called.append(True) or (True, "x"))
    at = run_section("system")
    next(b for b in at.button if b.label == "Restart the server computer").click().run()
    next(b for b in at.button if b.label == "Cancel").click().run()
    assert called == [] and "Restart the server computer" in labels(at)


def test_restart_services_failure_is_shown(seeded_db, monkeypatch):
    monkeypatch.setattr(system, "manager", lambda: "systemd")
    monkeypatch.setattr(system, "restart_services", lambda: (False, "This computer doesn't allow it yet."))
    at = run_section("system")
    next(b for b in at.button if b.label.startswith("Restart the dashboard")).click().run()
    next(b for b in at.button if b.label == "Yes, restart").click().run()
    assert "doesn't allow" in at.error[0].value
