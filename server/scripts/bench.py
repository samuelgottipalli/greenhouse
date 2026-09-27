"""
Benchmark the dashboard's database queries on synthetic data.

Usage (from the ``server/`` folder)::

    python -m scripts.bench                 # one year of data, 20 runs per query
    python -m scripts.bench --days 30 --runs 5
    python -m scripts.bench --devices 5          # five controllers, a year each

Creates a throwaway database in a temporary folder (the real database is never
touched), fills it with ``--days`` of readings every 5 minutes (temperature,
humidity, light), relay events every 20 minutes and weather every 15 minutes,
then prints the median time of each query the pages run. The target (PLAN 3.1)
is 50 ms or less per query for a year of data.
"""
import argparse
import sqlite3
import statistics
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

TARGET_MS = 50.0


def fill(path: Path, days: int, devices: int = 1) -> dict[str, int]:
    """
    Create a database and fill it with synthetic data.

    Args:
        path (Path): New database file.
        days (int): Days of history to generate, ending now.
        devices (int): Controllers to create and fill (IDs 1..devices).

    Returns:
        dict[str, int]: Rows written per table.
    """
    from core import migrations

    conn = migrations.connect(path)
    migrations.create_new(conn)
    for device_id in range(2, devices + 1):
        conn.execute("BEGIN")
        migrations.seed_device(conn, device_id, f"picow{device_id}")
        conn.execute("COMMIT")
    end = datetime.now(timezone.utc).replace(microsecond=0)
    start = end - timedelta(days=days)
    fmt = "%Y-%m-%d %H:%M:%S"

    def times(step_minutes):
        moment = start
        while moment <= end:
            yield moment.strftime(fmt)
            moment += timedelta(minutes=step_minutes)

    conn.execute("BEGIN")
    readings = [(d, measure, at, value) for d in range(1, devices + 1) for at in times(5)
                for measure, value in ((1, 21.0), (8, 50.0), (6, 30000.0))]
    conn.executemany("INSERT INTO sensor_readings VALUES (?, ?, ?, ?)", readings)
    events = [(d, 1 + i % 4, at, i % 2, "auto") for d in range(1, devices + 1) for i, at in enumerate(times(20))]
    conn.executemany(
        "INSERT INTO relay_events (device_id, relay_id, event_utc, state, source) VALUES (?, ?, ?, ?, ?)", events
    )
    weather = [(at, 39.5, -119.7, 1346.0, 10.0, 8.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0, 5.0, 200.0, at, at)
               for at in times(15)]
    conn.executemany("INSERT INTO weather_readings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", weather)
    conn.execute("COMMIT")
    conn.execute("ANALYZE")
    conn.close()
    return {"sensor_readings": len(readings), "relay_events": len(events), "weather_readings": len(weather)}


def measure(runs: int, device_id: int = 1) -> dict[str, float]:
    """
    Time each page query against the configured database.

    Args:
        runs (int): Repetitions per query; the median is reported.
        device_id (int): Controller whose pages are timed.

    Returns:
        dict[str, float]: Query name to median milliseconds.
    """
    from core import db
    from core.timeutil import utc_timestamp

    now = datetime.now(timezone.utc)
    queries = {
        "latest_sensor_readings": lambda: db.latest_sensor_readings(device_id=device_id),
        "latest_relay_states": lambda: db.latest_relay_states(device_id=device_id),
        "sensor_history_24h": lambda: db.sensor_history(utc_timestamp(now - timedelta(days=1)), device_id=device_id),
        "sensor_history_7d_hourly": lambda: db.sensor_history(
            utc_timestamp(now - timedelta(days=7)), device_id=device_id, bucket="hour"),
        "sensor_history_30d_hourly": lambda: db.sensor_history(
            utc_timestamp(now - timedelta(days=30)), device_id=device_id, bucket="hour"),
        "recent_weather": db.recent_weather,
        "read_thresholds": db.read_thresholds,
        "relay_names": db.relay_names,
    }
    results = {}
    for name, query in queries.items():
        query()  # warm up
        samples = []
        for _ in range(runs):
            started = time.perf_counter()
            query()
            samples.append((time.perf_counter() - started) * 1000)
        results[name] = statistics.median(samples)
    return results


def main(argv: list[str] | None = None) -> int:
    """
    Build the synthetic database, run the benchmark and print a report.

    Returns:
        int: 0 if every query meets the target, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--devices", type=int, default=1, help="controllers to simulate (pages timed for the last)")
    args = parser.parse_args(argv)

    from core import db, settings

    original_url = settings.DB_URL
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "bench.db"
        counts = fill(path, args.days, args.devices)
        settings.DB_URL = f"sqlite:///{path.as_posix()}"
        db.get_engine.cache_clear()
        try:
            print(f"Synthetic data for {args.days} days, {args.devices} device(s): {counts}")
            results = measure(args.runs, device_id=args.devices)
        finally:
            db.get_engine().dispose()
            settings.DB_URL = original_url
            db.get_engine.cache_clear()
    slow = 0
    for name, ms in results.items():
        flag = "ok" if ms <= TARGET_MS else "SLOW"
        slow += flag == "SLOW"
        print(f"{name:26} {ms:8.2f} ms  {flag}")
    return 1 if slow else 0


if __name__ == "__main__":
    raise SystemExit(main())
