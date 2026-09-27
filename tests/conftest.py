"""
Shared fixtures for the greenhouse test suite. See tests/support.py for the
environment set-up and fixture data.
"""
import sqlite3
from pathlib import Path

import pytest

from support import TEST_DB_PATH, build_db


@pytest.fixture
def seeded_db() -> Path:
    """Fresh fixture database at the path the app is configured to use."""
    build_db(TEST_DB_PATH)
    yield TEST_DB_PATH


@pytest.fixture
def db_conn(seeded_db):
    """Raw sqlite3 connection to the fixture database, for assertions."""
    conn = sqlite3.connect(seeded_db)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def no_real_mqtt(monkeypatch):
    """Make any MQTT publish a test did not mock fail at once, as if no broker were running."""
    from core import mqtt

    def refuse(**kwargs):
        raise ConnectionRefusedError("tests never talk to a real broker")

    monkeypatch.setattr(mqtt, "single", refuse)
