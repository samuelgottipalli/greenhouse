"""
Background service that records outdoor weather from the Open-Meteo API.

Run from the ``server/`` folder with ``python -m services.weather_collector``.
It stores one reading per 15-minute slot (:00, :15, :30, :45): the first pass
after a slot begins fetches and inserts a row into ``weather_readings``. A
failed fetch is retried once, 30 seconds later; after that the slot is
skipped. Remembering the last slot (instead of matching "second <= 10")
means a slot is never collected twice and never missed because a sleep ran
long.
"""
import logging
from datetime import datetime
from time import sleep

from core import db
from core.weather_api import clean_data, fetch_weather

log = logging.getLogger(__name__)

SLOT_MINUTES = 15
POLL_SECONDS = 10
RETRY_SECONDS = 30


def collect_once() -> bool:
    """
    Fetch the current weather and store it.

    Returns:
        bool: True if a row was stored.
    """
    return db.insert_weather(clean_data(fetch_weather()))


def slot_start(moment: datetime) -> datetime:
    """
    Return the start of the 15-minute slot containing a moment.

    Args:
        moment (datetime): Any time.

    Returns:
        datetime: The same time rounded down to :00, :15, :30 or :45.
    """
    return moment.replace(minute=moment.minute - moment.minute % SLOT_MINUTES, second=0, microsecond=0)


def run(now=datetime.now, pause=sleep, max_passes: int | None = None) -> None:
    """
    Collect once per slot, forever (or for ``max_passes`` loop passes).

    Args:
        now (callable): Returns the current time (injected in tests).
        pause (callable): Sleeps for a number of seconds (injected in tests).
        max_passes (int | None): Stop after this many passes; None runs forever.
    """
    last_slot = None
    passes = 0
    while max_passes is None or passes < max_passes:
        passes += 1
        slot = slot_start(now())
        if slot != last_slot:
            last_slot = slot
            stored = collect_once()
            if not stored:
                log.warning("Weather collection failed for %s; retrying in %s s", slot, RETRY_SECONDS)
                pause(RETRY_SECONDS)
                stored = collect_once()
            log.info("Slot %s stored: %s", slot, stored)
        pause(POLL_SECONDS)


def main() -> None:
    """Configure logging and run the collector forever."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()


if __name__ == "__main__":
    main()
