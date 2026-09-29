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

**Status (2026-09-27, after Phase 5):** 810 tests pass (plus one Linux-only test that CI runs) and no `known_bug` tests remain.
The controller runs the automation rules itself when the network is down (P-15). Both
directions of the device/server contract are tested end to end; what's left is confirming it on the
hardware ([RUNBOOK.md](RUNBOOK.md)).

✅ = done, 🟡 = partly done. See the tracking table at the end for notes.

---

## Phase 0: Safety and repo hygiene (about 1–2 days)

Goal: no secrets in the repo, a clean and reproducible setup, and tests running automatically.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 0.1 🟡 | (History scrubbed 2026-09-26; only the password change remains.) Change the Wi-Fi password and any real values in `.env` / `secrets.toml`. Untrack those files and `picoside/config.json`, and commit `config.example.json`, `.env.example` and `secrets.example.toml`. Optionally purge history with `git filter-repo` (needs a force-push). | SEC-01 | `git ls-files` lists no secret files; the templates exist; the old Wi-Fi password no longer works. | 2 h |
| 0.2 ✅ | Add `.gitattributes` (`* text=auto eol=lf`, `*.db binary`) and make one EOL-normalising commit. | R-01 | `git ls-files --eol` shows `i/lf` for all text files. | 30 min |
| 0.3 ✅ | Replace `requirements.txt` with a UTF-8 file listing only runtime packages, add `requirements-dev.txt` (pytest), and fix the `*.txt` rule in `.gitignore`. | S-16 | In a fresh venv, `pip install -r requirements-dev.txt` then `pytest` passes; the runtime file has 10 or fewer packages. | 1 h |
| 0.4 ✅ | Untrack `greenhouse.db`. `python -m scripts.upgrade_db` creates the schema from `core/schema.sql` and seeds the reference and default rows. | R-02 | A fresh clone plus `upgrade_db` gives an app where every page renders. | 2 h |
| 0.5 ✅ | Add a GitHub Actions workflow that runs `pytest` on push and PR (Python 3.11). | R-03 | A PR shows a green check; a deliberately failing test turns it red. | 1 h |

---

## Phase 1: Correctness fixes (about 4–6 days)

Goal: everything that exists today behaves correctly. Most steps turn one `known_bug` test green.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 1.1 ✅ | Move the automation rules into a pure function `automation.decide(conditions, readings, relay_states, now) -> list[Action]`. Send heater commands to relay 3. Evaluate the fan once on (temperature OR humidity) with hysteresis. Apply the heater buffer. Skip and log when data is missing or older than 15 min, with a sleep. `services/automation.py` becomes a thin loop around it. | S-06, S-01 (stale guard) | Table-driven tests cover on, off and hold for each relay, including the buffer edges; branch coverage of `automation.py` is 90 % or more; no command for relay 3 ever carries relay ID 2. | 1.5 d |
| 1.2 ✅ | Store times as `HH:MM` on save, and make the controller accept `HH:MM` and `HH:MM:SS`. | S-02 | `test_settings_save_keeps_hh_mm_time_format` passes; a controller test parses both formats. | 2 h |
| 1.3 ✅ | Work out the toggle action inside the callback from the widget's current value, and stamp `actiontime` at click time. Replace the four copied blocks with one loop over `d_relays`. | S-03, S-11 (part) | `test_control_first_toggle_off_sends_off` passes; `greenhousecontrol.py` shrinks by 100 or more lines. | 3 h |
| 1.4 ✅ | Weather page: show a "no readings yet today" state, compute deltas only with two or more rows, use `conversions.py` for all unit maths and the compass lookup. | S-04, S-05, S-07 | The three weather `known_bug` tests pass; a new test checks the US and SI values of one known row. | 3 h |
| 1.5 ✅ | Convert the buffers between °C and °F deltas on the Settings page. Show empty states on the Control and Settings pages when tables are empty. | S-08, S-09 | New tests: a 2 °F buffer saves as 1.11 °C; both pages render with empty tables. | 3 h |
| 1.6 ✅ | Pico MQTT: call `set_callback` before `subscribe`, and catch all connect errors. | P-01 | `test_real_client_connects_subscribes_and_receives` passes; the device boots against a real broker (manual check). | 1 h |
| 1.7 ✅ | Pico clock: GPS removed. The RTC is kept in UTC by NTP (at boot, then daily, retrying every 5 min until the first success). The LCD shows local time from `utc_offset_minutes` plus a `us`/`eu`/`none` DST rule, which `picoside/setup_config.py` derives from an IANA zone name. | P-02, S-17 (Pico side) | Offsets match `zoneinfo` for every hour of 2026–27 in six zones (`test_clock.py`); the device clock still reads correctly 48 h after boot (manual check). | 4 h |
| 1.8 ✅ | Weather collector: add `timeout=10` to requests, fire once per 15-minute slot by tracking the last slot, and retry once. | S-13 | Tests with mocked time show exactly one fetch per slot; a hung request times out. | 2 h |
| 1.9 ✅ | Portability: build paths from `Path(__file__).parent`, use forward-slash image paths, and fix the `HELP.md` name. | S-12 | Page tests pass when run from the repo root without `chdir`; the app starts on Linux. | 1 h |

---

## Phase 2: Close the loop (about 1 week)

Goal: sensor readings flow from the Pico into the database, and commands flow from the web and
automation to the physical relays, with confirmation.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 2.1 ✅ | Write `docs/MQTT.md`, the message contract. Proposed topics: `greenhouse/<device>/telemetry`, `greenhouse/<device>/relay/<n>/set` (absolute `on`/`off`, not toggle), `greenhouse/<device>/relay/<n>/state` (retained), `greenhouse/<device>/status` (`online`/`offline` via last will). JSON payloads with ISO-8601 UTC timestamps. | P-03 | The contract is reviewed; a schema test validates example payloads. | 3 h |
| 2.2 ✅ | Pico: subscribe to the `set` topics, call `check_msg()` in the main loop, set relays to absolute states, and publish `state` after every change, including button presses (action 031/030). Publish telemetry on the new topic. | P-03, P-06 | Firmware tests with the fake broker show that a `set` message drives the pin and publishes `state`; on hardware, a web toggle moves the relay (manual check). | 1.5 d |
| 2.3 ✅ | Server `ingest.py` (replaces `getgreenhousedata.py`): a paho client with auto-reconnect that writes telemetry to `greenhouse_data` and state messages to `relay_status`. Web and automation publish to `set` and treat the `state` echo as confirmation. | S-01 | Integration test with a fake paho client; a 24 h soak on hardware stores 99 % or more of the expected 288 telemetry rows. | 1.5 d |
| 2.4 ✅ | Turn on broker username/password and ACLs (device may publish only its own topics), and read the credentials from config on both sides. | SEC-02 | An anonymous `mosquitto_pub` to a `set` topic is rejected; the device and server still work. | 3 h |

**Phase exit check:** on the LAN, a web toggle to a confirmed relay state takes 2 s or less
(median of 20 tries). Telemetry is at most 6 minutes old at any time during a 24 h run.

---

## Phase 3: Reliability and performance (about 1 week)

Goal: runs unattended for weeks, and stays fast as data grows.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 3.1 ✅ | DB layer: one engine per process (`st.cache_resource` in the app, a module-level engine in services), `st.cache_data(ttl=60)` for reads, a primary key and index on `relay_status(deviceid, relayid, actiontime)` plus an index on `greenhouse_data`, and replace the bare-column `GROUP BY`. | S-10 | `scripts/bench.py` with one year of synthetic data (about 105k telemetry rows and 50k relay rows) shows each page query at 50 ms or less and a warm full page render at 500 ms or less. | 1 d |
| 3.2 ✅ | Pico robustness: `machine.WDT`, non-blocking Wi-Fi and MQTT reconnect with backoff, a ring buffer of the last 48 readings replayed on reconnect, button IRQs that only set flags, one shared `Display`, and `ticks_diff` everywhere. | P-04, P-05, P-07, P-08, P-09 | Firmware tests for the buffer and reconnect state machine; a 7-day soak with a 30-minute Wi-Fi outage each day shows no hang or reboot loop, and buffered readings arrive after reconnect. | 2 d |
| 3.3 ✅ | Services: switch to `logging` with rotating files, add systemd units (or one supervisor script) for `ingest`, `automation` and `weather`, and have each write a heartbeat row. | S-14 | `systemctl kill` restarts the service within 10 s; the Home page shows each service's last heartbeat. | 4 h |
| 3.4 ✅ | Retention: nightly job that rolls telemetry older than 90 days into hourly averages. | (scale) | The database grows by 5 MB/year or less per device (measured on synthetic data). | 3 h |

---

## Phase 4: Features and scale (about 2–3 weeks, pick in any order)

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 4.1 ✅ | Indoor dashboard (`greenhouse.py`): current temperature, humidity and light, plus 24 h / 7 d / 30 d history with high and low. Port the gauge and history ideas from the retired Dash app. | S-15 | Page test with fixture data; charts match the database values. | 1.5 d |
| 4.2 ✅ | Home page: system status (device online, reading age, relay states, service heartbeats, active alerts). | S-15 | Page test covers the online, stale and offline states. | 1 d |
| 4.3 ✅ | Manual override: per-relay `auto` / `manual until <time>` mode that the automation respects, reusing the Pico's `relay_modes`. | S-06 (5) | Automation tests: a manual toggle holds until expiry, then automation resumes. | 1 d |
| 4.4 ✅ | Multiple devices: drive devices and relays from `devices`/`relays`, add a device selector, and remove the fixed relay IDs in `services/automation.py` and `views/control.py`. | S-11 | No device or relay IDs are hard-coded outside seed data; tests run with two devices. | 1.5 d |
| 4.5 ✅ | Web login (Streamlit OIDC, or a reverse proxy with auth) and persistent per-user preferences in the database. | SEC-03, S-18 | Unauthenticated requests are redirected to login; preferences survive a browser restart. | 1 d |
| 4.6 ✅ | Alerts: temperature out of range, device offline, or service down, sent by email or push with a cooldown. | (feature) | A test triggers each alert once per cooldown window. | 1 d |
| 4.7 ✅ | Light automation from a calibrated LDR plus sunrise/sunset in `weather_data`. | P-10 | Calibration procedure documented; automation tests for day, night and cloudy cases. | 1 d |
| 4.8 ✅ | If more than about 5 devices or several years of data: move from SQLite to PostgreSQL/TimescaleDB. Only `DB_CONNECTION_STRING` and the SQL dialect should change. **Evaluated 2026-09-26: not needed.** `python -m scripts.bench --devices 5` (five controllers, a year of raw 5-minute readings each, 1.58 M rows, no retention) keeps every page query at 33 ms or less; with retention a device adds ~2.6 MB/year. SQLite now runs in WAL mode with a busy timeout so the four processes can write concurrently. Revisit if there are more than ~20 controllers, if `database is locked` appears in the logs, or if the dashboard must run on a different machine than the database. | (scale) | The test suite passes against Postgres in CI. | 1–2 d |

---

## Phase 5: Easy setup and updates (about 2 weeks)

Goal: someone who has never written code can set up the server and a controller, and later
update the controller's code without a USB cable.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 5.1 ✅ | **Controller setup hotspot.** With no Wi-Fi settings, or when the screen button is held at power-on, the Pico starts its own Wi-Fi network (`GreenhouseSetup-XXXX`, password shown on the LCD) and a setup page at `192.168.4.1`. Phones open it automatically (captive portal). The page lists nearby networks, takes the Wi-Fi password, a *setup code* from the dashboard (server address and login) and the time zone (guessed from the phone). If the new Wi-Fi can't be joined on the next boot, setup starts again with the error shown. A router outage never triggers setup; the controller keeps running on its own (local mode). | (usability) | Tests cover the page, form checks, DNS replies, setup code decoding, the time-zone table (checked against `zoneinfo`), and every way into and out of setup mode; all device files compile with `mpy-cross`. | 2 d |
| 5.2 ✅ | **Setup code on the dashboard.** Settings → Controllers shows each controller's setup code and a QR code, and remembers each controller's broker password (`server/data/device_credentials.json`, git-ignored). New setting `PUBLIC_HOST` (the address controllers use to reach this server; blank = detect). | (usability) | Round-trip test: a code made by the server is decoded by the device code into the same settings. | 0.5 d |
| 5.3 ✅ | **Over-the-air updates.** The server publishes a manifest (file list with SHA-256) of `picoside/device/`. The new `greenhouse-firmware` service serves the files over HTTP on the LAN. The dashboard shows *Update available* and an **Update controller** button. The controller downloads only the changed files, checks every hash, swaps them in, and restarts. The new code must reach the broker within 10 minutes and 3 restarts, or `boot.py` puts the old files back. Status goes on `greenhouse/<id>/firmware`; schema v6 stores it. | (feature) | Tests: good update, a corrupt download (nothing changes), a crash-looping update rolls back, a hung update rolls back, and the server's manifest matches what the device installs. | 3 d |
| 5.4 ✅ | **One-command server** (`server/run_all.py`) for Windows and macOS: runs the web app, services, broker and scheduled jobs, and restarts any that stop. Linux keeps systemd. | (usability) | Tests with stand-in processes: crash → restart with backoff; jobs run on schedule; clean shutdown. | 1 d |
| 5.5 ✅ | **Desktop installer** (`setup.bat` / `setup.sh` → PySide6 wizard): installs the packages, asks for location, time zone and dashboard password, installs and locks down Mosquitto (creating passwords), creates the database, starts the services (systemd on Linux, log-in start on Windows/macOS), then sets up the Pico over USB: installs MicroPython if needed, writes Wi-Fi settings (defaulting to this computer's network, warning about 5 GHz), copies the code and waits for the controller to come online. | (usability) | Logic tests for every step (env file, commands per OS, broker files, Pico file list, Wi-Fi detection); GUI smoke test runs offscreen in CI. | 4 d |
| 5.6 ✅ | Docs: a short *Quick start* for the installer and hotspot, RUNBOOK kept as the manual/advanced path, in-app Help updated. | (docs) | Docs tests check every referenced file and command exists. | 0.5 d |

## Phase 6: Version numbers people can read (about 2 days)

Goal: the dashboard, the controller and the installer say "1.1.0", not a code like `3f9a0c1b2d4e`,
and each release has a short list of what changed. Work happens on the `develop` branch; `main`
holds released versions only (tagged `v1.0.0`, `v1.1.0`, ...).

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 6.1 ✅ | **Version numbers.** `server/version.py` and `picoside/device/version.py` each hold a version like `1.1.0` (major.minor.patch: major = big or breaking change, minor = new features, patch = fixes only). While a release is being built it ends in `-dev`. `CHANGELOG.md` lists what changed in each release, in plain words. Releases are merged to `main` and tagged. | (usability) | Tests: both versions are valid, and `CHANGELOG.md` has an entry for each. | 0.5 d |
| 6.2 ✅ | **The controller says its version.** Update messages carry the version name next to the exact build (the file hash that was the only "version" before). The controller reports both, records the name with each update ("Updated from 1.0.0 to 1.1.0"), and shows its version on the screen while starting. 1.0.0 controllers still update: the manifest keeps the fields they read. | (usability) | Tests: a 1.0.0-style controller accepts the new manifest; a new controller reports name and build; rollback still works. | 0.5 d |
| 6.3 ✅ | **The dashboard shows versions.** Schema v7 stores the controller's version name. Settings › Controllers shows *Installed 1.1.0* / *Available 1.1.0* (with the build underneath for support); an update is offered when the build differs, or by name when the build is unknown. Help › About and the installer show the server version. | (usability) | Tests: migration, the update-available rule for known/unknown builds and old controllers, and the page text. | 0.5 d |
| 6.4 ✅ | **Installer records the build** when it copies the code over USB, so a freshly set-up controller doesn't show *Update available*. (Already in place since 5.5.) | (usability) | Test: the staged files include `firmware.json` with the manifest's build. | 0.25 d |

## Phase 7: Cloud MQTT services (about 4 days)

Goal: anyone who would rather not run Mosquitto can use a hosted MQTT service (for example HiveMQ
Cloud's free plan), with encrypted and verified connections from the server and the controllers.

| Step | Work | Fixes | Done when | Effort |
|---|---|---|---|---|
| 7.1 ✅ | **Encrypted connections from the server.** New settings `MQTT_TLS` (on automatically for port 8883) and `MQTT_CA_FILE` (optional). Every server connection (ingest, relay commands, settings, updates, installer checks) goes through one helper. | (feature) | Tests: each connection gets the login and TLS settings; a real TLS login to a public test broker in a network test (skipped offline). | 0.5 d |
| 7.2 ✅ | **Encrypted connections from the controller.** A small set of root certificates (Let's Encrypt, Amazon, DigiCert, GlobalSign, Google, Sectigo) ships in `picoside/device/certs/` as `.py` text files, so 1.0.0 controllers can still update to it. New config `mqtt_tls` and `mqtt_ca` (a root's name; empty = find the one that works and remember it). TLS waits for the clock (certificates have dates). | (feature) | Tests: context set-up, root discovery, a certificate that doesn't match is refused, clock-not-set handling. On the real Pico: verified connection to a Let's Encrypt broker, memory measured. | 1 d |
| 7.3 ✅ | **Setup codes and the setup page** carry *encrypted* and the root's name (`t`, `c`); the setup page's manual section gets an *Encrypted connection (TLS)* box. | (feature) | Round-trip tests of the new keys; old codes still decode. | 0.5 d |
| 7.4 ✅ | **Installer: "Use a cloud MQTT service".** Address, port 8883, the server's login and controller 1's login (both created in the service's console). It checks both logins over TLS and finds which bundled root the service uses, warning if none does. | (usability) | Logic tests for the page's choices and saved settings. | 1 d |
| 7.5 ✅ | **Dashboard and docs.** Settings › Controllers lets you type the controller's login name (cloud services choose their own) and builds the code with the cloud address. RUNBOOK gets a HiveMQ Cloud walkthrough; MQTT.md and Help are updated. Over-the-air updates still come from the server on your network. | (docs) | Docs tests; page tests for a cloud set-up. | 1 d |

## Phase 8: Run it on a cloud server, reachable from the internet (about 2 weeks)

Goal: someone can run their own copy on a cloud VM (a $4–6/month instance is plenty) and open the
dashboard from anywhere, safely. Today's design assumes a home network: plain HTTP for the
dashboard and for controller updates, one shared password, and the controllers reaching the server
directly. Each of those changes once the server is on the internet.

| Step | Work | Done when | Effort |
|---|---|---|---|
| 8.1 | **Packaged deployment.** One `docker compose` file: the dashboard and services, Mosquitto, and Caddy in front, which gets and renews HTTPS certificates automatically. Only ports 443 (dashboard) and 8883 (MQTT over TLS) are open. A short *Deploy to a cloud VM* guide (a domain name, DNS, `docker compose up`). | A fresh VM reaches a working dashboard over HTTPS by following the guide; CI builds the images. | 3 d |
| 8.2 | **Broker on the internet.** Mosquitto listens with TLS only (port 8883, the certificate Caddy obtains) and never allows anonymous logins; the controller already speaks TLS (Phase 7). Per-controller logins and topic rules as today. | Tests: the generated broker settings; a controller connects to a Let's Encrypt broker (done on hardware in Phase 7). | 2 d |
| 8.3 | **Updates over HTTPS.** Controllers download update files over HTTPS through Caddy instead of plain HTTP on port 8081 (the checksums already come over the encrypted MQTT link). Plain HTTP stays for home networks. | Tests: `https://` manifest URLs are accepted and checked; the controller update test runs over TLS. | 2 d |
| 8.4 | **Stronger login.** Separate accounts (owner, family members, view-only), passwords stored with a slow hash (already), a pause after repeated wrong passwords, optional sign-in with Google or Microsoft (OIDC), and a list of signed-in devices that can be logged out. Home installs keep the simple single password. | Tests: roles on each page, lock-out timing, OIDC sign-in against a test identity provider. | 4 d |
| 8.5 | **Hardening and backups.** Security headers and cookie flags behind HTTPS, the dashboard's own port closed to the outside, automatic daily database backups to object storage, and alerts when backups fail. A security checklist in the RUNBOOK. | A scan of the running VM (open ports, TLS grade, headers) passes the checklist; restoring a backup is tested. | 2 d |

**Is it viable?** Yes. The pieces that matter are already in place: encrypted, verified MQTT
from the controller (Phase 7), per-controller logins and topic rules, and a server that needs
little memory or disk (about 2.6 MB of readings per controller per year). The controller keeps
running its rules if the internet connection drops, so a cloud server is no less safe for the
plants than a home one. What must change is everything listed above that assumed a trusted home
network. Until Phase 8 is done, the safe way to reach a home server from outside is a private
network tool such as Tailscale, or Cloudflare Access in front of the dashboard.

## Phase 9: One service for many greenhouses (about 6–8 weeks)

Goal: a hosted version where people sign up, add their controller with the setup code, and never
run a server. Each account sees only its own greenhouses. This is the foundation for the free and
premium tiers (Phase 10); the self-hosted version stays free and keeps every feature.

| Step | Work | Done when | Effort |
|---|---|---|---|
| 9.1 | **Accounts and greenhouses.** Sign-up with email confirmation (and OIDC), accounts that own greenhouses, greenhouses that own controllers, and people invited to a greenhouse with a role. | Tests: every query is limited to the signed-in account; one account can never read or change another's data (tested for every page and service). | 2 wk |
| 9.2 | **Database for many users.** Move from SQLite to PostgreSQL with the account on every row, row-level security as a second guard, and data retention per plan. The same code keeps SQLite for self-hosting. | Migration tested both ways; the isolation tests from 9.1 pass on both databases. | 1.5 wk |
| 9.3 | **Adding a controller.** The dashboard creates the controller's own broker login, topic rules and setup code; the controller joins with the phone hotspot as today. Removing it revokes the login at once. A broker that manages logins through an API (Mosquitto's dynamic security plugin or EMQX). | A new account adds a real Pico by phone in under 5 minutes; a removed controller can no longer connect. | 1.5 wk |
| 9.4 | **Running the service.** Health monitoring and alerting for the service itself, error tracking, rate limits per account, and a status page. Updates roll out to controllers gradually (a few first, then everyone), each still able to roll itself back. | A load test with 1,000 simulated controllers stays within the plan's budget; a bad update stops rolling out automatically. | 1.5 wk |
| 9.5 | **The paperwork.** Terms of use, a privacy policy (what is stored, for how long, where; data export and account deletion), and how to contact support. | Both published; export and deletion work from the dashboard. | 0.5 wk |

The dashboard runs on Streamlit today, which is fine for one household. A shared service with
many users is likely to need a web API (e.g. FastAPI) with a separate front end; 9.1 starts by
measuring whether Streamlit copes, and makes that call.

## Phase 10: Free and premium plans (about 3 weeks)

Goal: a generous free plan that covers a typical home greenhouse completely, and a fairly priced
premium plan for bigger setups and extras that cost real money to run. Nothing to do with the
plants' safety or the basics of running a greenhouse is ever behind a paywall.

| | **Free** | **Premium** (about $3/month or $30/year) |
|---|---|---|
| Greenhouses and controllers | 1 greenhouse, up to 3 controllers | Up to 10 greenhouses, 25 controllers |
| Dashboard, gauges, charts, remote control | ✓ | ✓ |
| Automation rules, local mode, safety cut-offs | ✓ | ✓ |
| Software updates over Wi-Fi, with roll-back | ✓ | ✓ |
| Alerts | Email and push notifications | Also text messages (SMS) |
| History | 1 year of readings | Unlimited, full detail |
| Export your data (CSV) and delete your account | ✓ | ✓ |
| People sharing a greenhouse | 2 | Unlimited, with roles (owner, helper, view-only) |
| Weather | Local forecast | Forecast plus frost and heat warnings ahead of time |
| Extras | | Seasonal schedules, more than one zone per greenhouse, Home Assistant and webhooks, reports by email |
| Support | Community forum and guides | Email support |
| Self-hosting (your own server) | Always free, every feature, open source | — |

| Step | Work | Done when | Effort |
|---|---|---|---|
| 10.1 | **Plans in the product.** Limits enforced in one place with friendly messages (never a surprise cut-off: going over a limit warns first and keeps working for 30 days). Downgrading keeps all data; older history becomes read-only rather than deleted. | Tests for every limit, the grace period and downgrade. | 1 wk |
| 10.2 | **Billing.** Stripe checkout and customer portal (monthly or yearly, cancel any time, receipts), the plan shown on the account page. Discounts for schools and community gardens. | End-to-end tests against Stripe's test mode, including failed payments (grace period, not a lock-out). | 1 wk |
| 10.3 | **Premium extras**, one at a time: SMS alerts, frost warnings, seasonal schedules, zones, Home Assistant and webhooks. | Each ships with tests and a Help page. | ongoing |
| 10.4 | **Launch.** A small beta (friends and a gardening club) on the free plan first, then premium. Measure the running cost per active controller before fixing prices. | Beta feedback addressed; cost per controller measured and prices confirmed. | 1 wk |

Why these limits: a free account costs very little to run (a few MB of readings a year and a
handful of messages a minute), so the free plan can cover a typical home greenhouse completely.
The premium plan pays for things that cost more (text messages, unlimited storage, many
controllers, support time) and funds development.

## Phase 11: History and analysis (about 4 days)

(Phases 7–10 are on the `develop` branch.) Goal: look back over any period of the last six months,
compare each month with the same month last year, and keep the database small by summarising
old months instead of keeping every reading.

| Step | Work | Done when | Effort |
|---|---|---|---|
| 11.1 ✅ | **Periods and date ranges.** Both Reports tabs get 24 hours / 7 days / 30 days / **Date range** (any days in the last 6 months, local calendar days). Charts show every reading up to 2 days, hourly averages up to 45 days and daily averages beyond; rain as totals per hour or per day. Outdoor weather gains the History section the Greenhouse tab had. | Tests for periods, the queries (end dates, hourly rain totals, one place only), and both tabs with a date range. | 1.5 d |
| 11.2 ✅ | **Monthly summaries** (schema v8, `monthly_stats`): per controller and measure (temperature, humidity, light in lux) and for the weather (temperature, humidity, wind, rain as daily totals): samples, mean, median, 25th/75th and 2.5th/97.5th percentiles, min, max, and rain's monthly total. | Tests for the statistics, local month boundaries (daylight saving), lux and daily rain. | 0.5 d |
| 11.3 ✅ | **The monthly job** (`scripts.retention`, replacing the nightly hourly roll-up): summarise every finished month not yet summarised, back up the database, then delete readings older than 6 whole months, only once their months are summarised. It only does what is missing. Runs on the 1st at 03:30, at the next start if that was missed (`Persistent=true`), and 10 minutes after every start (`OnBootSec`); `run_all.py` runs it at start-up and daily. | Tests: summarise-then-trim, a second run does nothing, a missed 1st caught up, nothing deleted if a summary fails, backups rotate. On a year of synthetic data: 2.6 s, database 21 MB → 9.6 MB. | 1 d |
| 11.4 ✅ | **Analysis page**: Greenhouse and Outdoor weather tabs, a box plot per measure for the last 12 months plus this month so far (live), this month highlighted against the same month last year with a comparison sentence and the numbers underneath. | Page and chart tests; checked in Chrome on a year of synthetic data. | 1 d |

---

## Tracking

| Phase | Status | Notes |
|---|---|---|
| Review | Done | Overview, findings, docstrings, test harness, `serverside` retired |
| Housekeeping | Done | GPS removed; `server/` and `picoside/device/` layouts; schema v2/v3 plus migrations; Pico main loop rewritten |
| 0 | 0.2–0.5 ✅ · 0.1 🟡 | 0.1 needs you: change the Wi-Fi password (optionally rewrite history) |
| 1 | 1.1–1.9 ✅ | Hardware confirmations for 1.6/1.7 are in the RUNBOOK sign-off |
| 2 | 2.1–2.4 ✅ | 2.2 on-hardware check in the RUNBOOK sign-off. Added: controller local mode and sensor-fault heater cut-off (P-15), relay-state resync (P-14), send-before-log (S-19/S-20) |
| 3 | 3.1–3.4 ✅ | 3.2: 7-day soak simulated in tests; the on-hardware run is in the RUNBOOK sign-off. 3.3: heartbeats + systemd watchdog. 3.4: 2.6 MB/device/year measured |
| 4 | 4.1–4.8 ✅ | 4.8 evaluated and not needed at this scale (see the step); on-hardware checks for 4.6/4.7 are in the RUNBOOK sign-off |
| 5 | 5.1–5.6 ✅ | Installer (`setup.bat`/`setup.sh`), setup hotspot, setup codes, updates over Wi-Fi, `run_all.py`. On-hardware checks are in the RUNBOOK sign-off |
| 6 | 6.1–6.4 ✅ | Released as **1.1.0** (tag `v1.1.0`), with the location setting (Settings › Location); schema v7 stores the controller's version name |
| 7 | 7.1–7.5 ✅ | On `develop` as 1.2.0-dev (not deployed yet). Checked on the real Pico W against Let's Encrypt and DigiCert brokers (roots found by trying, a wrong root refused, ~30 KB RAM); found and fixed umqtt's timeouts on TLS sockets |
| 8 | Planned | Cloud VM deployment, reachable from the internet |
| 9 | Planned | Hosted service for many greenhouses |
| 10 | Planned | Free and premium plans |
| 11 | 11.1–11.4 ✅ | Reports periods and date ranges, monthly summaries and clean-up, Analysis page (schema v8) |

Bring-up on real hardware follows [RUNBOOK.md](RUNBOOK.md).
