"""
Alerts: detect problems and notify, at most once per cooldown per problem.

Conditions checked (``services/alerts.py`` runs this every 2 minutes):

* ``offline:<device>``: the controller reports offline (urgent).
* ``stale:<device>``: no reading for more than 15 minutes while the
  controller is not known to be offline.
* ``temp_low:<device>`` / ``temp_high:<device>``: a fresh temperature below
  ``ALERT_TEMP_LOW_C`` or above ``ALERT_TEMP_HIGH_C`` (urgent).
* ``service_down:<service>`` / ``service_degraded:<service>``: from the
  service heartbeats (``core/health.py``).

Each condition is stored in the ``alerts`` table. A new one is sent at once;
while it lasts it is repeated at most every ``ALERT_COOLDOWN_MIN``; when it
clears, one "resolved" message is sent. If sending fails it is retried on the
next run.
"""
import logging
from datetime import datetime, timedelta, timezone

from core import db, notify, settings
from core.automation import READING_MAX_AGE
from core.health import service_health
from core.timeutil import parse_utc_timestamp, utc_timestamp

log = logging.getLogger(__name__)


def current_conditions(now: datetime) -> dict[str, tuple[str, bool]]:
    """
    Find every problem that exists right now.

    Args:
        now (datetime): Current time (aware).

    Returns:
        dict[str, tuple[str, bool]]: Alert key to ``(message, urgent)``.
    """
    found: dict[str, tuple[str, bool]] = {}
    for device_id, name in (db.list_devices() or {}).items():
        status = db.device_status(device_id=device_id)
        if status and status["status"] == "offline":
            found[f"offline:{device_id}"] = (
                f"Controller {name} is offline (since {status['updated_utc']} UTC). "
                "It runs its own safety rules until it reconnects.", True)
            continue
        latest = db.latest_sensor_readings(device_id=device_id)
        if latest is None:
            continue  # never reported: nothing to compare yet
        rows = latest.set_index("measure")
        newest = parse_utc_timestamp(latest["reading_utc"].max())
        if now - newest > READING_MAX_AGE:
            minutes = int((now - newest).total_seconds() // 60)
            found[f"stale:{device_id}"] = (f"No readings from {name} for {minutes} minutes.", False)
            continue
        if "temperature" in rows.index and now - parse_utc_timestamp(rows.loc["temperature", "reading_utc"]) <= READING_MAX_AGE:
            temp = float(rows.loc["temperature", "value"])
            if temp < settings.ALERT_TEMP_LOW_C:
                found[f"temp_low:{device_id}"] = (
                    f"{name}: greenhouse is {temp:.1f} °C, below {settings.ALERT_TEMP_LOW_C:g} °C.", True)
            elif temp > settings.ALERT_TEMP_HIGH_C:
                found[f"temp_high:{device_id}"] = (
                    f"{name}: greenhouse is {temp:.1f} °C, above {settings.ALERT_TEMP_HIGH_C:g} °C.", True)
    for entry in service_health(now):
        if entry["status"] == "down":
            found[f"service_down:{entry['service']}"] = (
                f"The {entry['service']} service has not reported for over 2 minutes.", True)
        elif entry["status"] == "degraded":
            found[f"service_degraded:{entry['service']}"] = (
                f"The {entry['service']} service has a problem: {entry['detail'] or 'unhealthy'}.", False)
    return found


def process(now: datetime | None = None, send=notify.deliver) -> dict[str, int]:
    """
    Raise, repeat and resolve alerts, notifying as needed.

    Args:
        now (datetime | None): Current time (aware); defaults to now.
        send (callable): ``send(title, message, urgent) -> bool`` (injected in tests).

    Returns:
        dict[str, int]: Counts of ``raised``, ``repeated`` and ``resolved``
        notifications sent.
    """
    now = now or datetime.now(timezone.utc)
    stamp = utc_timestamp(now)
    cooldown = timedelta(minutes=settings.ALERT_COOLDOWN_MIN)
    conditions = current_conditions(now)
    stored = db.read_alerts()
    counts = {"raised": 0, "repeated": 0, "resolved": 0}

    for key, (message, urgent) in conditions.items():
        row = stored.get(key)
        if row is None or not row["active"]:
            db.save_alert(key, True, message, stamp, None)
            if send("Alert", message, urgent):
                db.save_alert(key, True, message, stamp, stamp)
                counts["raised"] += 1
            continue
        last = row["last_sent_utc"]
        if last is None or now - parse_utc_timestamp(last) >= cooldown:
            if send("Still a problem", f"{message} (since {row['since_utc']} UTC)", urgent):
                db.save_alert(key, True, message, row["since_utc"], stamp)
                counts["repeated"] += 1

    for key, row in stored.items():
        if row["active"] and key not in conditions:
            if send("Resolved", f"Resolved: {row['message']}", False):
                db.save_alert(key, False, row["message"], row["since_utc"], stamp)
                counts["resolved"] += 1
    return counts
