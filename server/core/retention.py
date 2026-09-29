"""
Data retention: raw readings are kept for 6 whole months, then summarised
per month and deleted. The work is in ``core/history.py`` (:func:`run_monthly`),
run by ``scripts/retention.py`` on the 1st of each month and after every
start of the server.

(Before 1.2.0 readings older than 90 days were averaged per hour and kept;
those hourly rows are summarised and deleted like any other once they are
older than 6 months.)
"""
import logging

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from core import db

log = logging.getLogger(__name__)


def vacuum() -> bool:
    """
    Return freed space to the file system (rewrites the database file).

    Returns:
        bool: True on success.
    """
    try:
        with db.get_engine().connect() as conn:
            conn.execute(text("VACUUM"))
    except SQLAlchemyError as err:
        log.error("VACUUM failed: %s", err)
        return False
    return True
