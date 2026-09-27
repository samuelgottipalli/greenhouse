"""
Report how completely a device's telemetry was stored over a recent period.

Usage (from the ``server/`` folder)::

    python -m scripts.telemetry_report              # last 24 hours, device from .env
    python -m scripts.telemetry_report --hours 48 --interval 300

Counts temperature readings (one per telemetry message) and compares them with
the number expected at the device's publish interval (default 300 s). Used for
the 24-hour check in docs/RUNBOOK.md: at least 99 % should be present.
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone

from core import db, settings
from core.timeutil import utc_timestamp

TARGET = 0.99


def coverage(hours: float, interval_s: int, device_id: int, now: datetime | None = None) -> tuple[int, int]:
    """
    Count stored and expected telemetry messages in the period.

    Args:
        hours (float): Length of the period, ending now.
        interval_s (int): Device publish interval in seconds.
        device_id (int): Device to check.
        now (datetime | None): End of the period (aware); defaults to now.

    Returns:
        tuple[int, int]: ``(stored, expected)``.
    """
    now = now or datetime.now(timezone.utc)
    history = db.sensor_history(utc_timestamp(now - timedelta(hours=hours)), device_id=device_id)
    stored = 0 if history is None else int((history["measure"] == "temperature").sum())
    return stored, int(hours * 3600 // interval_s)


def main(argv: list[str] | None = None) -> int:
    """
    Print the report.

    Returns:
        int: 0 if at least 99 % of expected messages were stored, else 1.
    """
    parser = argparse.ArgumentParser(description="Telemetry completeness report.")
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--interval", type=int, default=300, help="device publish_interval_s")
    parser.add_argument("--device", type=int, default=settings.DEVICE_ID)
    args = parser.parse_args(argv)
    stored, expected = coverage(args.hours, args.interval, args.device)
    share = stored / expected if expected else 0.0
    print(f"Device {args.device}, last {args.hours:g} h: {stored} of {expected} expected readings ({share:.1%})")
    return 0 if share >= TARGET else 1


if __name__ == "__main__":
    sys.exit(main())
