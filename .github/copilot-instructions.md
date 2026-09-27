## Greenhouse Project AI Agent Guidelines

This project has two components: `picoside/device` (MicroPython firmware for a Raspberry Pi Pico W)
and `server` (Streamlit web app plus background services). The old Dash app (`serverside`) and the
GPS module have been removed; do not reintroduce them.

Start with `README.md` for the overview, `docs/FINDINGS.md` for known defects, `docs/PLAN.md` for
planned work, `docs/MQTT.md` for the message contract and `docs/RUNBOOK.md` for hardware bring-up.

### 1. Layout

*   **`picoside/device/`**: exactly what is copied to the Pico.
    *   `main.py`: boot and the loop around `Controller.tick()`, with a watchdog.
    *   `controller.py`: main-loop logic (timers, buttons, screens, commands, telemetry).
    *   Hardware modules: `net.py` (Wi-Fi/MQTT with reconnect and outbox), `clock.py` (NTP, UTC to
        local with a DST rule), `display.py`, `relays.py`, `sensors.py`, `buttons.py` (IRQ handlers
        only queue events), `config.py` (defaults and legacy key upgrade).
    *   `lib/`: vendored third-party code (`lcd_api`, `i2c_lcd`, `umqtt.simple`).
*   **`picoside/setup_config.py`**: runs on a PC and writes `device/config.json` (git-ignored).
*   **`server/`** (run everything from this folder):
    *   `app.py`: Streamlit entry point (`streamlit run app.py`). Pages live in `views/` and use
        `ui.page_setup()`.
    *   `core/`: `settings.py` (the only place `.env` is read), `db.py` (all SQL), `schema.sql`
        (current schema, version in `PRAGMA user_version`), `migrations.py`, `mqtt.py`, `weather_api.py`, `timeutil.py`,
        `conversions.py`, `weather_codes.py`.
    *   `core/automation.py`: pure automation rules (`decide`); the service only feeds and acts on it.
    *   `core/alerts.py` + `core/notify.py`: alert conditions, cooldown, ntfy/email delivery (`services/alerts.py`, timer).
    *   `core/health.py`: `Heartbeat` (DB heartbeat + systemd watchdog); every service beats once per good pass.
    *   `services/`: `ingest.py`, `automation.py` and `weather_collector.py` (`python -m services.<name>`).
    *   `core/retention.py`: nightly roll-up of readings older than 90 days (run by `scripts/retention.py` via a systemd timer).
    *   `scripts/`: `upgrade_db` (create/migrate DB), `add_device` (register a controller), `set_password` (dashboard login), `bench` (query timings), `telemetry_report`, `retention`.
*   **`deploy/`**: systemd units + `install_services.py`; `mosquitto/` broker config and ACL.

### 2. Conventions

*   Timestamps are UTC text `YYYY-MM-DD HH:MM:SS` in columns ending `_utc`, and on the wire as
    `ts_utc`. Times of day are local `HH:MM`; durations are integer minutes.
*   Units go in names (`temperature_c`, `wind_speed_kmh`). Store SI units and convert for display
    with `core/conversions.py`.
*   Database tables are STRICT with integer IDs. `relay_events` stores `state` (0/1) and `source`
    (`auto`/`web`/`device`). Change the schema only through `core/migrations.py`, bumping
    `PRAGMA user_version`.
*   Device code must run on MicroPython: no type annotations, no `str.ljust`/`rjust` (use
    `"{:<20}".format`), and always use `time.ticks_diff`/`ticks_add` for ticks.
*   Google-style docstrings (`Args:` / `Returns:`) on all modules and functions.
*   Never commit real secrets (`server/.env`, `picoside/device/config.json`).

### 3. Testing

*   Run `python -m pytest` from the repository root. Install the tools with
    `pip install -r requirements-dev.txt`.
*   `tests/server/`: DB, migrations, MQTT, weather, automation and Streamlit `AppTest` page tests,
    against a temporary seeded database (`tests/support.py`).
*   `tests/picoside/`: firmware on CPython with fake hardware (`pico_fakes.py`, ticks wrap at
    2**30), plus an `mpy-cross` compile check of every device file.
*   Every change needs a test. Known defects are `known_bug` tests marked
    `xfail(strict=True)`. Remove the marker in the change that fixes the bug.
