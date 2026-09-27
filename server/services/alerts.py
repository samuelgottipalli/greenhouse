"""
Alert check, run every 2 minutes by ``greenhouse-alerts.timer``.

Run from the ``server/`` folder with ``python -m services.alerts``. It checks
for problems, sends new, repeated (after the cooldown) and resolved alerts,
and exits. Running from its own timer means it still works when the
long-running services are down, which is one of the things it reports.
"""
import logging
import sys

from core.alerts import process

log = logging.getLogger(__name__)


def main() -> int:
    """
    Run one alert check.

    Returns:
        int: Process exit code (0 even when alerts were sent).
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    counts = process()
    log.info("Alerts raised %(raised)s, repeated %(repeated)s, resolved %(resolved)s", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
