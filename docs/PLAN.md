# Improvement Plan

This plan fixes the problems in [FINDINGS.md](FINDINGS.md) and gets the system working end to end.
The phases are ordered by risk: security first, then correctness, then closing the data loop, then
robustness, then new features. Each step says:

- **Fixes**: the finding IDs it addresses.
- **Done when**: a check anyone can run to confirm the step is finished.
- **Effort**: a rough estimate of focused work for one person familiar with the code.

**Ground rules for every step**
- Every change comes with tests in `tests/`, and `pytest` stays green.
- A fix for a `known_bug` test removes that test's `xfail` marker in the same change.
- Firmware logic that can run on CPython is tested with the fake hardware in `tests/picoside/`.
  Anything that needs real hardware gets a short manual check listed under "Done when".
- One step per branch or PR, so each can be reviewed and reverted on its own.

**Baseline (2026-09-26, after housekeeping):** 223 tests pass, 5 `known_bug` tests xfail. The
device and server now use the same command format ([MQTT.md](MQTT.md)), but nothing stores device
telemetry yet (step 2.3).

✅ = done, 🟡 = partly done. See the tracking table at the end for notes.

---

## Phase 0: Safety and repo hygiene (about 1–2 days)

Goal: no secrets in the repo, a clean and reproducible setup, and tests running automatically.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 0.1 🟡 | Change the Wi-Fi password and any real values in `.env` / `secrets.toml`. Untrack those files and `picoside/config.json`, and commit `config.example.json`, `.env.example` and `secrets.example.toml`. Optionally purge history with `git filter-repo` (needs a force-push). | SEC-01 | `git ls-files` lists no secret files; the templates exist; the old Wi-Fi password no longer works. | 2 h |
| 0.2 | Add `.gitattributes` (`* text=auto eol=lf`, `*.db binary`) and make one EOL-normalising commit. | R-01 | `git ls-files --eol` shows `i/lf` for all text files. | 30 min |
| 0.3 ✅ | Replace `requirements.txt` with a UTF-8 file listing only runtime packages, add `requirements-dev.txt` (pytest), and fix the `*.txt` rule in `.gitignore`. | S-16 | In a fresh venv, `pip install -r requirements-dev.txt` then `pytest` passes; the runtime file has 10 or fewer packages. | 1 h |
| 0.4 🟡 | Untrack `greenhouse.db`. Add `scripts/init_db.py` to create the schema from `greenhouse.sql` and seed the lookup and default rows, reusing the seed data in `tests/support.py`. | R-02 | A fresh clone plus `init_db.py` gives an app where every page renders. | 2 h |
| 0.5 | Add a GitHub Actions workflow that runs `pytest` on push and PR (Python 3.11). | R-03 | A PR shows a green check; a deliberately failing test turns it red. | 1 h |

---

## Phase 1: Correctness fixes (about 4–6 days)

Goal: everything that exists today behaves correctly. Most steps turn one `known_bug` test green.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 1.1 | Move the automation rules into a pure function `automation.decide(conditions, readings, relay_states, now) -> list[Action]`. Send heater commands to relay 3. Evaluate the fan once on (temperature OR humidity) with hysteresis. Apply the heater buffer. Skip and log when data is missing or older than 15 min, with a sleep. `services/automation.py` becomes a thin loop around it. | S-06, S-01 (stale guard) | Table-driven tests cover on, off and hold for each relay, including the buffer edges; branch coverage of `automation.py` is 90 % or more; no command for relay 3 ever carries relay ID 2. | 1.5 d |
| 1.2 ✅ | Store times as `HH:MM` on save, and make the controller accept `HH:MM` and `HH:MM:SS`. | S-02 | `test_settings_save_keeps_hh_mm_time_format` passes; a controller test parses both formats. | 2 h |
| 1.3 | Work out the toggle action inside the callback from the widget's current value, and stamp `actiontime` at click time. Replace the four copied blocks with one loop over `d_relays`. | S-03, S-11 (part) | `test_control_first_toggle_off_sends_off` passes; `greenhousecontrol.py` shrinks by 100 or more lines. | 3 h |
| 1.4 | Weather page: show a "no readings yet today" state, compute deltas only with two or more rows, use `conversions.py` for all unit maths and the compass lookup. | S-04, S-05, S-07 | The three weather `known_bug` tests pass; a new test checks the US and SI values of one known row. | 3 h |
| 1.5 | Convert the buffers between °C and °F deltas on the Settings page. Show empty states on the Control and Settings pages when tables are empty. | S-08, S-09 | New tests: a 2 °F buffer saves as 1.11 °C; both pages render with empty tables. | 3 h |
| 1.6 ✅ | Pico MQTT: call `set_callback` before `subscribe`, and catch all connect errors. | P-01 | `test_real_client_connects_subscribes_and_receives` passes; the device boots against a real broker (manual check). | 1 h |
| 1.7 ✅ | Pico clock: GPS removed. The RTC is kept in UTC by NTP (at boot, then daily, retrying every 5 min until the first success). The LCD shows local time from `utc_offset_minutes` plus a `us`/`eu`/`none` DST rule, which `picoside/setup_config.py` derives from an IANA zone name. | P-02, S-17 (Pico side) | Offsets match `zoneinfo` for every hour of 2026–27 in six zones (`test_clock.py`); the device clock still reads correctly 48 h after boot (manual check). | 4 h |
| 1.8 | Weather collector: add `timeout=10` to requests, fire once per 15-minute slot by tracking the last slot, and retry once. | S-13 | Tests with mocked time show exactly one fetch per slot; a hung request times out. | 2 h |
| 1.9 ✅ | Portability: build paths from `Path(__file__).parent`, use forward-slash image paths, and fix the `HELP.md` name. | S-12 | Page tests pass when run from the repo root without `chdir`; the app starts on Linux. | 1 h |

---

## Phase 2: Close the loop (about 1 week)

Goal: sensor readings flow from the Pico into the database, and commands flow from the web and
automation to the physical relays, with confirmation.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 2.1 ✅ | Write `docs/MQTT.md`, the message contract. Proposed topics: `greenhouse/<device>/telemetry`, `greenhouse/<device>/relay/<n>/set` (absolute `on`/`off`, not toggle), `greenhouse/<device>/relay/<n>/state` (retained), `greenhouse/<device>/status` (`online`/`offline` via last will). JSON payloads with ISO-8601 UTC timestamps. | P-03 | The contract is reviewed; a schema test validates example payloads. | 3 h |
| 2.2 ✅ | Pico: subscribe to the `set` topics, call `check_msg()` in the main loop, set relays to absolute states, and publish `state` after every change, including button presses (action 031/030). Publish telemetry on the new topic. | P-03, P-06 | Firmware tests with the fake broker show that a `set` message drives the pin and publishes `state`; on hardware, a web toggle moves the relay (manual check). | 1.5 d |
| 2.3 | Server `ingest.py` (replaces `getgreenhousedata.py`): a paho client with auto-reconnect that writes telemetry to `greenhouse_data` and state messages to `relay_status`. Web and automation publish to `set` and treat the `state` echo as confirmation. | S-01 | Integration test with a fake paho client; a 24 h soak on hardware stores 99 % or more of the expected 288 telemetry rows. | 1.5 d |
| 2.4 🟡 | Turn on broker username/password and ACLs (device may publish only its own topics), and read the credentials from config on both sides. | SEC-02 | An anonymous `mosquitto_pub` to a `set` topic is rejected; the device and server still work. | 3 h |

**Phase exit check:** on the LAN, a web toggle to a confirmed relay state takes 2 s or less
(median of 20 tries). Telemetry is at most 6 minutes old at any time during a 24 h run.

---

## Phase 3: Reliability and performance (about 1 week)

Goal: runs unattended for weeks, and stays fast as data grows.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 3.1 🟡 | DB layer: one engine per process (`st.cache_resource` in the app, a module-level engine in services), `st.cache_data(ttl=60)` for reads, a primary key and index on `relay_status(deviceid, relayid, actiontime)` plus an index on `greenhouse_data`, and replace the bare-column `GROUP BY`. | S-10 | `scripts/bench.py` with one year of synthetic data (about 105k telemetry rows and 50k relay rows) shows each page query at 50 ms or less and a warm full page render at 500 ms or less. | 1 d |
| 3.2 🟡 | Pico robustness: `machine.WDT`, non-blocking Wi-Fi and MQTT reconnect with backoff, a ring buffer of the last 48 readings replayed on reconnect, button IRQs that only set flags, one shared `Display`, and `ticks_diff` everywhere. | P-04, P-05, P-07, P-08, P-09 | Firmware tests for the buffer and reconnect state machine; a 7-day soak with a 30-minute Wi-Fi outage each day shows no hang or reboot loop, and buffered readings arrive after reconnect. | 2 d |
| 3.3 | Services: switch to `logging` with rotating files, add systemd units (or one supervisor script) for `ingest`, `automation` and `weather`, and have each write a heartbeat row. | S-14 | `systemctl kill` restarts the service within 10 s; the Home page shows each service's last heartbeat. | 4 h |
| 3.4 | Retention: nightly job that rolls telemetry older than 90 days into hourly averages. | (scale) | The database grows by 5 MB/year or less per device (measured on synthetic data). | 3 h |

---

## Phase 4: Features and scale (about 2–3 weeks, pick in any order)

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 4.1 | Indoor dashboard (`greenhouse.py`): current temperature, humidity and light, plus 24 h / 7 d / 30 d history with high and low. Port the gauge and history ideas from the retired Dash app. | S-15 | Page test with fixture data; charts match the database values. | 1.5 d |
| 4.2 | Home page: system status (device online, reading age, relay states, service heartbeats, active alerts). | S-15 | Page test covers the online, stale and offline states. | 1 d |
| 4.3 | Manual override: per-relay `auto` / `manual until <time>` mode that the automation respects, reusing the Pico's `relay_modes`. | S-06 (5) | Automation tests: a manual toggle holds until expiry, then automation resumes. | 1 d |
| 4.4 | Multiple devices: drive devices and relays from `devices`/`relays`, add a device selector, and remove the fixed relay IDs in `services/automation.py` and `views/control.py`. | S-11 | No device or relay IDs are hard-coded outside seed data; tests run with two devices. | 1.5 d |
| 4.5 | Web login (Streamlit OIDC, or a reverse proxy with auth) and persistent per-user preferences in the database. | SEC-03, S-18 | Unauthenticated requests are redirected to login; preferences survive a browser restart. | 1 d |
| 4.6 | Alerts: temperature out of range, device offline, or service down, sent by email or push with a cooldown. | (feature) | A test triggers each alert once per cooldown window. | 1 d |
| 4.7 | Light automation from a calibrated LDR plus sunrise/sunset in `weather_data`. | P-10 | Calibration procedure documented; automation tests for day, night and cloudy cases. | 1 d |
| 4.8 | If more than about 5 devices or several years of data: move from SQLite to PostgreSQL/TimescaleDB. Only `DB_CONNECTION_STRING` and the SQL dialect should change. | (scale) | The test suite passes against Postgres in CI. | 1–2 d |

---

## Tracking

| Phase | Steps | Status |
|---|---|---|
| Review | Overview, findings, docstrings, test harness, `serverside` retired | Done |
| Housekeeping | GPS removed; `server/` and `picoside/device/` layouts; schema v2 plus migration; Pico main loop rewritten | Done |
| 0 | 0.1 🟡 (files untracked with templates; credentials not yet rotated) · 0.3 ✅ · 0.4 🟡 (`scripts.upgrade_db` creates or migrates the database; the file is still tracked) · 0.2, 0.5 open | In progress |
| 1 | 1.2 ✅ (schema) · 1.6 ✅ · 1.7 ✅ (NTP + DST rule instead of GPS) · 1.9 ✅ · 1.1, 1.3–1.5, 1.8 open | In progress |
| 2 | 2.1 ✅ · 2.2 ✅ (needs a hardware check) · 2.4 🟡 (credentials supported on both sides; broker not locked down) · 2.3 open | In progress |
| 3 | 3.1 🟡 (one engine, index on `relay_events`; no read cache or benchmark) · 3.2 🟡 (all code done; 7-day soak not run) · 3.3, 3.4 open | In progress |
| 4 | 4.1–4.8 | Not started |

Progress at a glance: `pytest -rx` lists the remaining `known_bug` tests. Phase 1 is complete when
that list is empty.
