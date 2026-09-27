"""
Make a consistent backup of the live database.

Usage (from the ``server/`` folder)::

    python -m scripts.backup_db                     # data/greenhouse.backup-<time>.db
    python -m scripts.backup_db /mnt/usb/greenhouse.db

Uses SQLite's backup API, so it is safe while the services are running and
includes recent changes still in the WAL file (a plain file copy may miss
them).
"""
import sys
from datetime import datetime
from pathlib import Path

from core import migrations, settings


def main(argv: list[str] | None = None) -> int:
    """
    Back up the configured database.

    Args:
        argv (list[str] | None): Optional target path.

    Returns:
        int: Process exit code.
    """
    argv = sys.argv[1:] if argv is None else argv
    source = settings.sqlite_path(settings.DB_URL)
    if source is None or not source.exists():
        print("Error: no SQLite database file to back up", file=sys.stderr)
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(argv[0]) if argv else source.with_name(f"{source.stem}.backup-{stamp}{source.suffix}")
    conn = migrations.connect(source)
    try:
        migrations.backup_to(conn, target)
    finally:
        conn.close()
    print(f"Backed up {source} to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
