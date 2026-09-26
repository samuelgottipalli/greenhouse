"""
Create the database, or upgrade it to the current schema.

Usage (from the ``server/`` folder)::

    python -m scripts.upgrade_db               # database from DB_CONNECTION_STRING
    python -m scripts.upgrade_db path/to/file.db

Safe to run repeatedly. A version 1 database is backed up before migrating.
"""
import logging
import sys
from pathlib import Path

from core.migrations import upgrade


def main(argv: list[str]) -> int:
    """
    Run the upgrade and print the result.

    Args:
        argv (list[str]): Command-line arguments; an optional database path.

    Returns:
        int: Process exit code (0 on success, 1 on failure).
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        print(upgrade(Path(argv[0]) if argv else None))
    except RuntimeError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
