"""
Run the whole greenhouse server with one command (Windows and macOS).

Linux machines use systemd (``deploy/install_services.py``). Elsewhere, run
from the ``server/`` folder::

    python run_all.py

or let the installer start it when you log in. It starts and watches:

* the web app (Streamlit on port 8501) and the ``ingest``, ``automation``,
  ``weather`` and ``firmware`` services; any that stops is started again
  after 5 s, backing off to 60 s if it keeps failing;
* the MQTT broker, when the installer set one up here
  (``data/mosquitto/mosquitto.conf``) and Mosquitto is installed;
* the scheduled jobs: alerts every 2 minutes, and the monthly job (summaries
  for the Analysis page, then clean-up of readings older than 6 months) at
  start-up and daily at 03:30; it only does what is missing, so on most days
  it finds nothing to do.

Each program's output goes to ``data/logs/<name>.log``. Ctrl+C (or logging
out) stops everything.
"""
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
DATA_DIR = SERVER_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
BROKER_CONFIG = DATA_DIR / "mosquitto" / "mosquitto.conf"
RESTART_MIN_S = 5
RESTART_MAX_S = 60
HEALTHY_AFTER_S = 60
STOP_WAIT_S = 10
MOSQUITTO_PLACES = (
    r"C:\Program Files\mosquitto\mosquitto.exe",
    r"C:\Program Files (x86)\mosquitto\mosquitto.exe",
    "/opt/homebrew/sbin/mosquitto",
    "/usr/local/sbin/mosquitto",
    "/usr/sbin/mosquitto",
)

log = logging.getLogger("run_all")


def find_mosquitto(name: str = "mosquitto") -> str | None:
    """
    Find a Mosquitto program (``mosquitto`` or ``mosquitto_passwd``).

    Args:
        name (str): Program name.

    Returns:
        str | None: Full path, or None if it isn't installed.
    """
    found = shutil.which(name)
    if found:
        return found
    for place in MOSQUITTO_PLACES:
        candidate = Path(place).with_name(Path(place).name.replace("mosquitto", name, 1))
        if candidate.exists():
            return str(candidate)
    return None


def python_command(*args: str) -> list[str]:
    """A command that runs this Python with ``args``."""
    return [sys.executable, *args]


def programs(broker_config: Path = BROKER_CONFIG) -> dict[str, list[str]]:
    """
    The long-running programs to keep going.

    Args:
        broker_config (Path): Broker settings written by the installer.

    Returns:
        dict[str, list[str]]: Name -> command. The broker is included only
        when its settings file exists and Mosquitto is installed.
    """
    commands = {}
    mosquitto = find_mosquitto() if broker_config.exists() else None
    if mosquitto:
        commands["broker"] = [mosquitto, "-c", str(broker_config)]
    commands.update({
        "web": python_command("-m", "streamlit", "run", "app.py", "--server.headless", "true",
                              "--server.address", "0.0.0.0", "--server.port", "8501"),
        "ingest": python_command("-m", "services.ingest"),
        "automation": python_command("-m", "services.automation"),
        "weather": python_command("-m", "services.weather_collector"),
        "firmware": python_command("-m", "services.firmware_server"),
    })
    return commands


class Child:
    """
    One long-running program, restarted with backoff when it stops.

    Attributes:
        name (str): Short name (also the log file name).
        command (list[str]): Program and arguments.
        process (subprocess.Popen | None): Running process.
        restarts (int): How many times it was started again.
    """

    def __init__(self, name: str, command: list[str]):
        self.name = name
        self.command = command
        self.process = None
        self.restarts = 0
        self.started_at = None
        self.next_start = 0.0
        self.backoff = RESTART_MIN_S

    def check(self, now: float, launch) -> None:
        """
        Start the program if it isn't running and its restart delay has passed.

        Args:
            now (float): Monotonic seconds.
            launch (callable): ``launch(name, command)`` -> process.
        """
        if self.process is not None:
            code = self.process.poll()
            if code is None:
                if now - self.started_at >= HEALTHY_AFTER_S:
                    self.backoff = RESTART_MIN_S  # it ran long enough: forgive earlier crashes
                return
            log.warning("%s stopped (exit code %s); restarting in %s s", self.name, code, self.backoff)
            self.process = None
            self.next_start = now + self.backoff
            self.backoff = min(self.backoff * 2, RESTART_MAX_S)
            self.restarts += 1
        if now >= self.next_start:
            self.process = launch(self.name, self.command)
            self.started_at = now


class Job:
    """
    A short program run on a schedule: every ``every_s`` seconds, or daily at
    ``daily_at`` (``"HH:MM"``, local time), and optionally once as soon as the
    supervisor starts (``at_start``). A run is skipped while the last one is
    still going.
    """

    def __init__(self, name: str, command: list[str], every_s: int | None = None,
                 daily_at: str | None = None, started: float = 0.0, at_start: bool = False):
        self.name = name
        self.command = command
        self.every_s = every_s
        self.daily_at = daily_at
        self.process = None
        self.last_start = started
        self.last_day = None
        self.runs = 0
        self.start_pending = at_start

    def due(self, now: float, today: datetime) -> bool:
        """
        Tell whether the job should start now.

        Args:
            now (float): Monotonic seconds.
            today (datetime): Local date and time.

        Returns:
            bool: True if it is time and the last run has finished.
        """
        if self.process is not None and self.process.poll() is None:
            return False
        if self.start_pending:
            return True
        if self.every_s is not None:
            return now - self.last_start >= self.every_s
        return today.strftime("%H:%M") >= self.daily_at and self.last_day != today.date()

    def check(self, now: float, today: datetime, launch) -> None:
        """Start the job if it is due."""
        if self.due(now, today):
            at_start, self.start_pending = self.start_pending, False
            self.process = launch(self.name, self.command)
            self.last_start = now
            if not at_start or today.strftime("%H:%M") >= (self.daily_at or ""):
                self.last_day = today.date()
            self.runs += 1


class Supervisor:
    """Keeps the programs running and the jobs on schedule."""

    def __init__(self, children: list[Child], jobs: list[Job], popen=subprocess.Popen,
                 clock=time.monotonic, local_now=datetime.now, log_dir: Path = LOG_DIR):
        self.children = children
        self.jobs = jobs
        self.popen = popen
        self.clock = clock
        self.local_now = local_now
        self.log_dir = log_dir
        self.stopping = False

    def launch(self, name: str, command: list[str]):
        """
        Start a program with its output appended to ``<log_dir>/<name>.log``.

        Args:
            name (str): Program name.
            command (list[str]): Program and arguments.

        Returns:
            subprocess.Popen: The process.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        output = open(self.log_dir / f"{name}.log", "ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console windows on Windows
        log.info("starting %s", name)
        try:
            return self.popen(command, cwd=SERVER_DIR, stdout=output, stderr=subprocess.STDOUT,
                              env=dict(os.environ, PYTHONUNBUFFERED="1"), creationflags=flags)
        finally:
            output.close()  # the child keeps its own copy

    def step(self) -> None:
        """One pass: restart stopped programs and start due jobs."""
        now, today = self.clock(), self.local_now()
        for child in self.children:
            child.check(now, self.launch)
        for job in self.jobs:
            job.check(now, today, self.launch)

    def stop(self) -> None:
        """Stop every program and job: politely first, then forcefully."""
        self.stopping = True
        processes = [p.process for p in self.children + self.jobs if p.process is not None]
        for process in processes:
            if process.poll() is None:
                process.terminate()
        deadline = self.clock() + STOP_WAIT_S
        for process in processes:
            try:
                process.wait(timeout=max(0.0, deadline - self.clock()))
            except subprocess.TimeoutExpired:
                process.kill()

    def run(self, pause=time.sleep, max_steps: int | None = None) -> None:
        """
        Supervise until interrupted (Ctrl+C) or ``max_steps`` passes.

        Args:
            pause (callable): Sleep function (injected in tests).
            max_steps (int | None): Stop after this many passes.
        """
        steps = 0
        try:
            while not self.stopping and (max_steps is None or steps < max_steps):
                self.step()
                steps += 1
                pause(1)
        except KeyboardInterrupt:
            log.info("stopping")
        finally:
            self.stop()


def build(broker_config: Path = BROKER_CONFIG, started: float | None = None) -> Supervisor:
    """
    Build the supervisor for this server.

    Args:
        broker_config (Path): Broker settings written by the installer.
        started (float | None): Monotonic start time (alerts first run 2 min later).

    Returns:
        Supervisor: Ready to :meth:`Supervisor.run`.
    """
    started = time.monotonic() if started is None else started
    children = [Child(name, command) for name, command in programs(broker_config).items()]
    jobs = [
        Job("alerts", python_command("-m", "services.alerts"), every_s=120, started=started),
        Job("retention", python_command("-m", "scripts.retention"), daily_at="03:30", at_start=True),
    ]
    return Supervisor(children, jobs)


def main() -> int:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    supervisor = build()
    names = ", ".join(child.name for child in supervisor.children)
    log.info("Greenhouse server: running %s. Dashboard: http://localhost:8501  (Ctrl+C stops)", names)
    supervisor.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
