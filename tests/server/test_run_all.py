"""
Tests for server/run_all.py, the one-command server for Windows and macOS,
with stand-in processes and clocks.
"""
import subprocess
import sys
from datetime import datetime

import pytest

import run_all


class FakeProcess:
    def __init__(self, command):
        self.command = command
        self.code = None
        self.terminated = False
        self.killed = False
        self.stubborn = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self.code = -15

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.code

    def kill(self):
        self.killed = True
        self.code = -9


class Harness:
    """A supervisor whose processes and clocks the test controls."""

    def __init__(self, tmp_path, children, jobs=()):
        self.now = 1000.0
        self.local = datetime(2026, 9, 27, 12, 0)
        self.started = []
        self.supervisor = run_all.Supervisor(
            children, list(jobs), popen=self.popen, clock=lambda: self.now,
            local_now=lambda: self.local, log_dir=tmp_path / "logs")

    def popen(self, command, **kwargs):
        assert kwargs["cwd"] == run_all.SERVER_DIR
        assert kwargs["stderr"] == subprocess.STDOUT
        process = FakeProcess(command)
        self.started.append(process)
        return process

    def step(self, advance=0):
        self.now += advance
        self.supervisor.step()


def test_programs_without_broker(tmp_path):
    commands = run_all.programs(tmp_path / "none.conf")
    assert list(commands) == ["web", "ingest", "automation", "weather", "firmware"]
    assert commands["ingest"] == [sys.executable, "-m", "services.ingest"]
    assert commands["web"][1:4] == ["-m", "streamlit", "run"]


def test_programs_with_broker(tmp_path, monkeypatch):
    conf = tmp_path / "mosquitto.conf"
    conf.write_text("listener 1883\n")
    monkeypatch.setattr(run_all, "find_mosquitto", lambda name="mosquitto": "/usr/sbin/mosquitto")
    commands = run_all.programs(conf)
    assert list(commands)[0] == "broker"
    assert commands["broker"] == ["/usr/sbin/mosquitto", "-c", str(conf)]


def test_broker_config_but_no_mosquitto(tmp_path, monkeypatch):
    conf = tmp_path / "mosquitto.conf"
    conf.write_text("")
    monkeypatch.setattr(run_all, "find_mosquitto", lambda name="mosquitto": None)
    assert "broker" not in run_all.programs(conf)


def test_find_mosquitto_in_known_places(monkeypatch, tmp_path):
    exe = tmp_path / "mosquitto.exe"
    exe.write_text("")
    monkeypatch.setattr(run_all.shutil, "which", lambda name: None)
    monkeypatch.setattr(run_all, "MOSQUITTO_PLACES", (str(exe),))
    assert run_all.find_mosquitto() == str(exe)
    assert run_all.find_mosquitto("mosquitto_passwd") is None
    (tmp_path / "mosquitto_passwd.exe").write_text("")
    assert run_all.find_mosquitto("mosquitto_passwd") == str(tmp_path / "mosquitto_passwd.exe")


def test_starts_everything_and_logs(tmp_path):
    h = Harness(tmp_path, [run_all.Child("a", ["a"]), run_all.Child("b", ["b"])])
    h.step()
    assert [p.command for p in h.started] == [["a"], ["b"]]
    assert (tmp_path / "logs" / "a.log").exists()
    h.step(1)
    assert len(h.started) == 2  # still running: nothing new


def test_restarts_with_backoff(tmp_path):
    child = run_all.Child("ingest", ["ingest"])
    h = Harness(tmp_path, [child])
    h.step()
    h.started[-1].code = 1  # crash
    h.step(1)
    assert len(h.started) == 1 and child.restarts == 1  # waits 5 s
    h.step(5)
    assert len(h.started) == 2
    h.started[-1].code = 1
    h.step(1)
    h.step(5)
    assert len(h.started) == 2  # now waits 10 s
    h.step(5)
    assert len(h.started) == 3
    for _ in range(10):  # keeps crashing: the wait tops out at 60 s
        h.started[-1].code = 1
        h.step(1)
        h.step(60)
    assert child.backoff == run_all.RESTART_MAX_S


def test_backoff_forgiven_after_running_a_while(tmp_path):
    child = run_all.Child("web", ["web"])
    h = Harness(tmp_path, [child])
    h.step()
    for _ in range(3):
        h.started[-1].code = 1
        h.step(1)
        h.step(60)
    assert child.backoff > run_all.RESTART_MIN_S
    h.step(run_all.HEALTHY_AFTER_S)
    assert child.backoff == run_all.RESTART_MIN_S


def test_interval_job(tmp_path):
    job = run_all.Job("alerts", ["alerts"], every_s=120, started=1000.0)
    h = Harness(tmp_path, [], [job])
    h.step()
    h.step(119)
    assert job.runs == 0  # first run 2 minutes after start
    h.step(1)
    assert job.runs == 1
    h.step(120)
    assert job.runs == 1  # the last run hasn't finished: skipped
    h.started[-1].code = 0
    h.step(0)
    assert job.runs == 2


def test_job_at_start_then_daily(tmp_path):
    """The monthly job runs as soon as the server starts (catching up a missed 1st), then daily."""
    job = run_all.Job("retention", ["retention"], daily_at="03:30", at_start=True)
    h = Harness(tmp_path, [], [job])
    h.local = datetime(2026, 10, 1, 1, 0)  # started before 03:30
    h.step()
    assert job.runs == 1
    h.started[-1].code = 0
    h.step()
    assert job.runs == 1  # once
    h.local = datetime(2026, 10, 1, 3, 30)
    h.step()
    assert job.runs == 2  # that day's 03:30 run still happens


def test_daily_job(tmp_path):
    job = run_all.Job("retention", ["retention"], daily_at="03:30")
    h = Harness(tmp_path, [], [job])
    h.local = datetime(2026, 9, 27, 3, 29)
    h.step()
    assert job.runs == 0
    h.local = datetime(2026, 9, 27, 3, 30)
    h.step()
    assert job.runs == 1
    h.started[-1].code = 0
    h.local = datetime(2026, 9, 27, 23, 0)
    h.step()
    assert job.runs == 1  # once a day
    h.local = datetime(2026, 9, 28, 3, 31)
    h.step()
    assert job.runs == 2


def test_stop_terminates_then_kills(tmp_path):
    h = Harness(tmp_path, [run_all.Child("a", ["a"]), run_all.Child("b", ["b"])])
    h.step()
    polite, stubborn = h.started
    stubborn.stubborn = True
    h.supervisor.stop()
    assert polite.terminated and not polite.killed
    assert stubborn.terminated and stubborn.killed


def test_run_stops_cleanly_on_ctrl_c(tmp_path):
    h = Harness(tmp_path, [run_all.Child("a", ["a"])])
    calls = []

    def pause(seconds):
        calls.append(seconds)
        if len(calls) == 3:
            raise KeyboardInterrupt

    h.supervisor.run(pause=pause)
    assert h.started[0].terminated and h.supervisor.stopping


def test_build_has_services_and_jobs(tmp_path):
    supervisor = run_all.build(tmp_path / "none.conf", started=0.0)
    assert [c.name for c in supervisor.children] == ["web", "ingest", "automation", "weather", "firmware"]
    assert {j.name: (j.every_s, j.daily_at) for j in supervisor.jobs} == {
        "alerts": (120, None), "retention": (None, "03:30")}
    assert [j.name for j in supervisor.jobs if j.start_pending] == ["retention"]  # also once at start


@pytest.mark.parametrize("name", ["ingest", "automation", "weather_collector", "firmware_server", "alerts"])
def test_service_modules_exist(name):
    assert (run_all.SERVER_DIR / "services" / f"{name}.py").exists()


def test_real_launch_writes_log(tmp_path):
    """A real child process: output lands in its log file."""
    supervisor = run_all.Supervisor([], [], log_dir=tmp_path)
    process = supervisor.launch("echo", [sys.executable, "-c", "print('hello from child')"])
    assert process.wait(timeout=30) == 0
    assert "hello from child" in (tmp_path / "echo.log").read_text()
