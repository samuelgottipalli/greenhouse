"""
Background service that records outdoor weather from the Open-Meteo API.

Run from the ``server/`` folder with ``python -m services.weather_collector``.
Fetches once at start-up, then every 15 minutes (on :00, :15, :30, :45), and
inserts one row into ``weather_readings``.
"""
import logging
from datetime import datetime as dtt
from time import sleep

from core import db
from core.weather_api import clean_data, fetch_weather

log = logging.getLogger(__name__)


def collect_once() -> bool:
    """
    Fetch the current weather and store it.

    Returns:
        bool: True if a row was stored.
    """
    return db.insert_weather(clean_data(fetch_weather()))


def main() -> None:
    """Collect at start-up and then every 15 minutes, forever."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log.info("Stored: %s", collect_once())
    sleep(10)
    while True:
        if dtt.now().minute % 15 == 0 and 0 <= dtt.now().second <= 10:
            log.info("Stored: %s", collect_once())
        sleep(10)


if __name__ == "__main__":
    main()
