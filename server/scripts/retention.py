"""
Roll old sensor readings up into hourly averages (nightly job).

Usage (from the ``server/`` folder)::

    python -m scripts.retention                # keep 90 days raw, then VACUUM
    python -m scripts.retention --days 30 --no-vacuum
    python -m scripts.retention --measure      # size check on synthetic data

Installed as ``greenhouse-retention.timer`` (daily at 03:30) by
``deploy/install_services.py``. ``--measure`` builds throwaway databases with
one and two years of synthetic readings, applies retention, and prints the
yearly growth per device (target, PLAN 3.4: 5 MB or less).
"""
import argparse
import logging
import sys
import tempfile
from pathlib import Path

from core import db, retention, settings

TARGET_MB_PER_YEAR = 5.0


def run(keep_days: int, do_vacuum: bool) -> int:
    """
    Apply retention to the configured database.

    Returns:
        int: Process exit code.
    """
    cutoff = retention.cutoff_for(keep_days)
    result = retention.roll_up(cutoff)
    if result is None:
        return 1
    print(f"Readings before {cutoff}: {result['removed']} raw rows -> {result['added']} hourly rows; "
          f"{result['weather_removed']} weather snapshots thinned")
    if do_vacuum and (result["removed"] or result["weather_removed"]) and not retention.vacuum():
        return 1
    return 0


def measure(keep_days: int = retention.KEEP_RAW_DAYS) -> float:
    """
    Measure yearly database growth per device with retention applied.

    Builds one-year and two-year synthetic databases, applies retention and
    VACUUM to each, and returns the size difference.

    Returns:
        float: Megabytes added per year.
    """
    from scripts import bench

    sizes = []
    original_url = settings.DB_URL
    try:
        with tempfile.TemporaryDirectory() as folder:
            for years in (1, 2):
                path = Path(folder) / f"{years}y.db"
                bench.fill(path, 365 * years)
                settings.DB_URL = f"sqlite:///{path.as_posix()}"
                db.get_engine.cache_clear()
                retention.roll_up(retention.cutoff_for(keep_days))
                retention.vacuum()
                db.get_engine().dispose()
                sizes.append(path.stat().st_size / 1_000_000)
                print(f"{years} year(s) of data after retention: {sizes[-1]:.1f} MB")
    finally:
        settings.DB_URL = original_url
        db.get_engine.cache_clear()
    growth = sizes[1] - sizes[0]
    print(f"Growth: {growth:.2f} MB per year per device (target {TARGET_MB_PER_YEAR} MB)")
    return growth


def main(argv: list[str] | None = None) -> int:
    """
    Command-line entry point.

    Returns:
        int: Process exit code.
    """
    parser = argparse.ArgumentParser(description="Roll old readings into hourly averages.")
    parser.add_argument("--days", type=int, default=retention.KEEP_RAW_DAYS, help="days of raw readings to keep")
    parser.add_argument("--no-vacuum", action="store_true", help="skip VACUUM afterwards")
    parser.add_argument("--measure", action="store_true", help="measure yearly growth on synthetic data")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.measure:
        return 0 if measure(args.days) <= TARGET_MB_PER_YEAR else 1
    return run(args.days, not args.no_vacuum)


if __name__ == "__main__":
    sys.exit(main())
