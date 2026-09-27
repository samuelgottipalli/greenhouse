-- Greenhouse database schema, version 5.
--
-- Conventions
--   * Tables are STRICT: SQLite rejects values of the wrong type (needs SQLite >= 3.37).
--   * IDs are INTEGER.
--   * Timestamps are UTC text 'YYYY-MM-DD HH:MM:SS' in columns ending _utc.
--   * Times of day are local (server TIMEZONE) text 'HH:MM'; durations are INTEGER minutes.
--   * Physical units are part of the column/threshold name (_c, _pct, _mm, _kmh, ...).
--   * Settings have two profiles: 'current' (in use) and 'default' (factory values).

CREATE TABLE devices (
    device_id INTEGER PRIMARY KEY,
    name      TEXT    NOT NULL UNIQUE
) STRICT;

CREATE TABLE relays (
    device_id INTEGER NOT NULL REFERENCES devices (device_id) ON DELETE CASCADE,
    relay_id  INTEGER NOT NULL CHECK (relay_id BETWEEN 1 AND 8),
    name      TEXT    NOT NULL,
    PRIMARY KEY (device_id, relay_id),
    UNIQUE (device_id, name)
) STRICT;

CREATE TABLE measures (
    measure_id INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL UNIQUE,
    si_unit    TEXT    NOT NULL,
    us_unit    TEXT    NOT NULL
) STRICT;

-- One row per sensor value reported by a device.
CREATE TABLE sensor_readings (
    device_id   INTEGER NOT NULL REFERENCES devices (device_id) ON DELETE CASCADE,
    measure_id  INTEGER NOT NULL REFERENCES measures (measure_id),
    reading_utc TEXT    NOT NULL
        CHECK (reading_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    value       REAL    NOT NULL,
    PRIMARY KEY (device_id, measure_id, reading_utc)
) STRICT, WITHOUT ROWID;

-- Append-only log of relay changes. source: who asked for the change.
CREATE TABLE relay_events (
    event_id  INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL,
    relay_id  INTEGER NOT NULL,
    event_utc TEXT    NOT NULL
        CHECK (event_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    state     INTEGER NOT NULL CHECK (state IN (0, 1)),
    source    TEXT    NOT NULL CHECK (source IN ('auto', 'web', 'device')),
    FOREIGN KEY (device_id, relay_id) REFERENCES relays (device_id, relay_id) ON DELETE CASCADE
) STRICT;

CREATE INDEX relay_events_latest ON relay_events (device_id, relay_id, event_utc);

-- Automation thresholds. buffer is the hysteresis in the same unit as value.
CREATE TABLE thresholds (
    device_id INTEGER NOT NULL,
    profile   TEXT    NOT NULL CHECK (profile IN ('current', 'default')),
    name      TEXT    NOT NULL
        CHECK (name IN ('fan_on_temp_c', 'fan_on_humidity_pct', 'heater_on_temp_c', 'light_on_level')),
    relay_id  INTEGER NOT NULL,
    value     REAL    NOT NULL,
    buffer    REAL    NOT NULL DEFAULT 0 CHECK (buffer >= 0),
    PRIMARY KEY (device_id, profile, name),
    FOREIGN KEY (device_id, relay_id) REFERENCES relays (device_id, relay_id) ON DELETE CASCADE
) STRICT;

-- Daily watering slots. duration_min = 0 disables a slot.
CREATE TABLE watering_schedule (
    device_id    INTEGER NOT NULL,
    profile      TEXT    NOT NULL CHECK (profile IN ('current', 'default')),
    slot         INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 4),
    relay_id     INTEGER NOT NULL,
    start_local  TEXT    NOT NULL CHECK (start_local GLOB '[0-2][0-9]:[0-5][0-9]'),
    duration_min INTEGER NOT NULL CHECK (duration_min BETWEEN 0 AND 1440),
    PRIMARY KEY (device_id, profile, slot),
    FOREIGN KEY (device_id, relay_id) REFERENCES relays (device_id, relay_id) ON DELETE CASCADE
) STRICT;

-- Outdoor weather from Open-Meteo (requested without a timezone, so times are UTC).
CREATE TABLE weather_readings (
    measured_utc           TEXT PRIMARY KEY
        CHECK (measured_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    latitude               REAL NOT NULL,
    longitude              REAL NOT NULL,
    elevation_m            REAL,
    temperature_c          REAL,
    apparent_temperature_c REAL,
    relative_humidity_pct  REAL,
    precipitation_mm       REAL,
    rain_mm                REAL,
    showers_mm             REAL,
    snowfall_cm            REAL,
    weather_code           INTEGER,
    wind_speed_kmh         REAL,
    wind_direction_deg     REAL,
    sunrise_utc            TEXT,
    sunset_utc             TEXT
) STRICT;

-- Latest online/offline status per device (MQTT status topic) and its health
-- as last reported in telemetry.
CREATE TABLE device_status (
    device_id     INTEGER PRIMARY KEY REFERENCES devices (device_id) ON DELETE CASCADE,
    status        TEXT    NOT NULL CHECK (status IN ('online', 'offline')),
    updated_utc   TEXT    NOT NULL
        CHECK (updated_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    last_seen_utc TEXT,
    uptime_s      INTEGER,
    mem_free      INTEGER,
    rssi_dbm      INTEGER
) STRICT;

-- Dashboard display preferences (units, formats, zone), shared by all sessions.
CREATE TABLE app_preferences (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

-- Last sign of life from each background service (core/health.py).
CREATE TABLE service_heartbeats (
    service     TEXT PRIMARY KEY,
    updated_utc TEXT NOT NULL
        CHECK (updated_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    healthy     INTEGER NOT NULL DEFAULT 1 CHECK (healthy IN (0, 1)),
    detail      TEXT NOT NULL DEFAULT ''
) STRICT;

-- Alerts raised by services/alerts.py: one row per condition (e.g. 'temp_high:1').
CREATE TABLE alerts (
    alert_key     TEXT PRIMARY KEY,
    active        INTEGER NOT NULL CHECK (active IN (0, 1)),
    message       TEXT    NOT NULL,
    since_utc     TEXT    NOT NULL
        CHECK (since_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]'),
    last_sent_utc TEXT
        CHECK (last_sent_utc IS NULL OR last_sent_utc GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]')
) STRICT;

PRAGMA user_version = 5;
