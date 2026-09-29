"""
The monthly job: summarise finished months for the Analysis page, then
delete raw readings older than 6 whole months (``core/history.py``).

Usage (from the ``server/`` folder)::

    python -m scripts.retention                   # what the schedule runs
    python -m scripts.retention --keep-months 12

Scheduled by ``greenhouse-retention.timer`` on the 1st of each month and a few
minutes after every start (which catches up a missed 1st), and by
``run_all.py`` on Windows and macOS. It only does what is missing, so running
it again, or by hand, is safe. The database is copied to
``server/data/backups/`` before anything is deleted.
"""
import argparse
import logging
import sys

from core import history


def main(argv: list[str] | None = None) -> int:
    """
    Command-line entry point.

    Returns:
        int: 0 on success, 1 if something failed (see the log).
    """
    parser = argparse.ArgumentParser(description="Monthly summaries and clean-up of old readings.")
    parser.add_argument("--keep-months", type=int, default=history.KEEP_RAW_MONTHS,
                        help="whole months of raw readings to keep (default %(default)s)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = history.run_monthly(keep_months=args.keep_months)
    summarised = report["summarised"]
    print(f"Summarised {len(summarised)} month(s)" + (f": {', '.join(summarised)}" if summarised else ""))
    if report["deleted"]:
        print(f"Deleted readings before {report['cutoff_utc']} UTC: {report['deleted']['sensor_rows']} greenhouse, "
              f"{report['deleted']['weather_rows']} weather (backup: {report['backup']})")
    else:
        print(f"Nothing older than {report['cutoff_utc']} UTC to delete")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
