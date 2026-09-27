"""
Service health: heartbeats in the database and the systemd watchdog.

Each background service creates a :class:`Heartbeat` and calls
:meth:`Heartbeat.beat` once per successful pass. That does two things:

* Pings the systemd watchdog (``WATCHDOG=1`` on ``$NOTIFY_SOCKET``) every
  call. The units set ``WatchdogSec=120``, so a service that stops beating
  (hung, or failing every pass) is killed and restarted by systemd. Outside
  systemd (development, Windows, tests) this does nothing.
* Writes a row to ``service_heartbeats`` at most every ``every_s`` seconds,
  with whether the service is doing its job (``healthy``) and a short detail.
  The Home page shows these; a heartbeat older than ``STALE_AFTER_S`` means
  the service is down.
"""
import logging
import os
import socket
import time
from datetime import datetime, timezone

from core import db
from core.timeutil import parse_utc_timestamp, utc_timestamp

log = logging.getLogger(__name__)

HEARTBEAT_EVERY_S = 30
STALE_AFTER_S = 120
SERVICES: tuple[str, ...] = ("ingest", "automation", "weather")


def sd_notify(message: str) -> bool:
    """
    Send a notification to systemd (e.g. ``"WATCHDOG=1"``).

    Args:
        message (str): Notification text.

    Returns:
        bool: True if sent; False when not running under systemd.
    """
    address = os.environ.get("NOTIFY_SOCKET")
    if not address or not hasattr(socket, "AF_UNIX"):
        return False
    if address.startswith("@"):
        address = "\0" + address[1:]  # abstract socket
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode())
    except OSError as err:
        log.warning("systemd notify failed: %s", err)
        return False
    return True


class Heartbeat:
    """
    Throttled heartbeat for one service.

    Attributes:
        service (str): Name shown on the Home page, e.g. ``"ingest"``.
    """

    def __init__(self, service: str, every_s: float = HEARTBEAT_EVERY_S, clock=time.monotonic):
        """
        Args:
            service (str): Service name.
            every_s (float): Minimum seconds between database writes.
            clock (callable): Monotonic clock (injected in tests).
        """
        self.service = service
        self._every_s = every_s
        self._clock = clock
        self._last_write = None
        self._last_state = None

    def beat(self, healthy: bool = True, detail: str = "") -> bool:
        """
        Report that the service is alive.

        The database row is written when ``every_s`` has passed or when
        ``healthy``/``detail`` changed, so a problem shows up at once.

        Args:
            healthy (bool): Whether the service is doing its job.
            detail (str): Short status, e.g. ``"broker unreachable"``.

        Returns:
            bool: True if a row was written.
        """
        sd_notify("WATCHDOG=1")
        now = self._clock()
        state = (healthy, detail)
        due = self._last_write is None or now - self._last_write >= self._every_s
        if not due and state == self._last_state:
            return False
        if db.record_heartbeat(self.service, healthy, detail):
            self._last_write, self._last_state = now, state
            return True
        return False


def service_health(now: datetime | None = None) -> list[dict]:
    """
    Summarise every expected service for display.

    Args:
        now (datetime | None): Current time (aware); defaults to now.

    Returns:
        list[dict]: One dict per service in ``SERVICES`` with ``service``,
        ``status`` (``"ok"``, ``"degraded"``, ``"down"`` or ``"unknown"``),
        ``updated_utc`` and ``detail``.
    """
    now = now or datetime.now(timezone.utc)
    rows = db.read_heartbeats()
    known = {} if rows is None else rows.set_index("service").to_dict("index")
    summary = []
    for service in SERVICES:
        row = known.get(service)
        if row is None:
            summary.append({"service": service, "status": "unknown", "updated_utc": None, "detail": ""})
            continue
        age = (now - parse_utc_timestamp(row["updated_utc"])).total_seconds()
        if age > STALE_AFTER_S:
            status = "down"
        else:
            status = "ok" if row["healthy"] else "degraded"
        summary.append({"service": service, "status": status, "updated_utc": row["updated_utc"], "detail": row["detail"]})
    return summary


def signal_quality(rssi_dbm: int | None) -> str:
    """
    Describe Wi-Fi signal strength in words.

    Args:
        rssi_dbm (int | None): Signal in dBm.

    Returns:
        str: ``"good"`` (-60 or better), ``"fair"`` (down to -75), ``"weak"``,
        or ``"unknown"``.
    """
    if rssi_dbm is None:
        return "unknown"
    if rssi_dbm >= -60:
        return "good"
    return "fair" if rssi_dbm >= -75 else "weak"


def format_duration(seconds: int | None) -> str:
    """
    Format an uptime compactly.

    Args:
        seconds (int | None): Duration in seconds.

    Returns:
        str: e.g. ``"45 s"``, ``"12 min"``, ``"5 h 3 min"``, ``"3 d 4 h"``, or ``"?"``.
    """
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min"
    if seconds < 86400:
        return f"{seconds // 3600} h {seconds % 3600 // 60} min"
    return f"{seconds // 86400} d {seconds % 86400 // 3600} h"
