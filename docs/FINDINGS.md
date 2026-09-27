# Code Review Findings

Review of `picoside/` and `server-streamlit/` as of 2026-09-26. Each finding has an ID that
[PLAN.md](PLAN.md) refers to.

**Evidence** tells you how the finding was confirmed:
- **Test**: reproduced by a test in `tests/` marked `known_bug` / `xfail(strict=True)`. When the
  bug is fixed that test starts passing, pytest reports it as `XPASS(strict)` and fails. Remove the
  marker at that point.
- **Code**: found by reading the code, with the reasoning given below. Not yet reproduced on
  hardware.

Severity: **Critical** means unsafe or broken core function. **High** means wrong behaviour users
will hit. **Medium** means robustness or maintainability. **Low** means cleanup.

## Summary

**Status** is as of the housekeeping pass on 2026-09-26, which removed GPS, reorganised both code
trees, moved the database to schema version 2 and rewrote the Pico main loop. The detail sections
below still use the file paths from review time: `server-streamlit/` is now `server/` (with
`core/`, `views/` and `services/` subfolders), and `picoside/` is now `picoside/device/`.

| ID | Severity | Area | Finding | Evidence | Status |
|----|----------|------|---------|----------|--------|
| SEC-01 | Critical | Repo | Wi-Fi password and app secrets are committed to git | Code | **Fixed in git**: secret files untracked (templates only), and on 2026-09-26 the whole history was rewritten to remove them, all databases and caches, and every Wi-Fi/secret value (verified: 0 occurrences). **Still to do:** change the Wi-Fi password, since GitHub caches or older clones may still hold the old commits |
| SEC-02 | High | MQTT | Broker traffic is unauthenticated and unencrypted; anyone on the LAN can switch relays | Code | **Fixed in repo**: `deploy/mosquitto/` turns off anonymous access and limits each account to its own topics (tested against the topics the code uses); both sides send credentials. Applying it on the broker is RUNBOOK step 2 |
| SEC-03 | High | Web | Web app has no login; anyone who can reach the port can switch the heater or water | Code | **Fixed**: password login on every page (salted PBKDF2 hash in `.env`, set with `python -m scripts.set_password`); an unset password shows a warning |
| P-01 | Critical | Pico | Boot crashes as soon as a real MQTT broker is configured | Test | **Fixed**: callback set before subscribe; test passes |
| P-02 | Critical | Pico | Clock "sync" re-applies the time-zone offset; after the first midnight the clock loops | Code | **Fixed**: GPS removed; RTC kept in UTC via NTP (re-synced daily); local time from offset plus DST rule |
| P-03 | Critical | Pico/Server | Relay commands from the server never reach the relays (topic/payload mismatch, no polling) | Code | Partial: both directions verified end to end in `test_contract_with_server.py`; remaining check is on real hardware (docs/RUNBOOK.md) |
| S-01 | Critical | Server | No service stores Pico sensor data; automation runs on stale readings | Code + DB | **Fixed**: `services/ingest.py` stores telemetry, relay changes and status (tested end to end against the firmware code); automation ignores readings older than 15 min |
| S-06 | Critical | Server | Automation loop bugs: heater commands go to the fan, conflicting fan logic, busy loop | Test + Code | **Fixed**: rules moved to pure `core/automation.py` (100% branch-tested): heater drives relay 3, one fan decision with hysteresis, heater buffer, no busy loop, 60-min manual override |
| S-02 | High | Server | Saving settings stores `HH:MM:SS`; the automation service then crashes parsing `HH:MM` | Test | **Fixed**: schema stores `HH:MM` and whole minutes |
| S-03 | High | Web | First toggle after page load sends the opposite command | Test | **Fixed**: the callback reads the new toggle value and time when clicked; toggles always show the logged state |
| S-04 | High | Web | Weather page crashes if there are fewer than two readings for today | Test | **Fixed**: shows "no readings yet today" with the last reading time; deltas and charts only with two or more readings |
| S-05 | High | Web | Weather page crashes when wind is from 348.75-360 degrees | Test | **Fixed**: compass lookup via `degrees_to_compass_index` (wraps 360° to N) |
| S-07 | High | Web | Weather unit conversions are wrong (apparent temp, precipitation, snowfall) | Code | **Fixed**: all conversions in `core/weather_report.py` using the tested `conversions.py` helpers |
| P-04 | Medium | Pico | Blocking work inside button handlers (10 s sleep); LCD written from two contexts | Code | **Fixed**: handlers only queue events; the loop does the work |
| P-05 | Medium | Pico | No Wi-Fi reconnect, no watchdog, readings dropped while offline | Code | **Fixed**: backoff reconnect, watchdog, 48-message outbox, keep-alive and last will |
| P-06 | Medium | Pico | Button presses change relays without telling the server | Code | **Fixed**: every change publishes a retained state message |
| P-07 | Medium | Pico | `ticks_ms` wrap-around: uptime and double-press detection break after ~12 days | Code | **Fixed**, with a wrap test |
| P-08 | Low | Pico | Five separate `Display` objects and config loads at import | Code | **Fixed**: one of each, passed in |
| P-09 | Low | Pico | `relay_control` assigns a local instead of the global `last_relay_display_update` | Code | **Fixed** (loop rewritten) |
| P-10 | Low | Pico | LDR is a raw ADC value but the light threshold is labelled in lumens | Code | **Fixed**: measure is `light_raw` (brighter = higher; `ldr_inverted` for reversed wiring); calibration procedure in RUNBOOK; grow light automated in daytime (PLAN 4.7) |
| P-11 | High | Pico | Screen and IP buttons are swapped (pull-up reads 0 when pressed), and the 500 ms debounce made double-press impossible | Code | **Fixed** (found during the rewrite) |
| P-12 | Medium | Pico | First sensor reading comes 5 minutes after boot, so the LCD shows no values until then | Code | **Fixed**: first read and publish at boot |
| P-13 | Low | Pico | Vendored `umqtt` printed debug output on every message check and had no socket timeout | Code | **Fixed** |
| S-08 | Medium | Web | Hysteresis buffers are shown as °F but stored and used as °C | Code | **Fixed**: buffers converted as temperature differences (2 °C = 3.6 °F) on display and save |
| S-09 | Medium | Web | Control and Settings pages crash on an empty database | Code | **Fixed**: Settings and Control show an error when the tables are missing; Control shows relays with no history as off |
| S-10 | Medium | Server | New DB engine per query, never disposed; no indexes on the growing log tables | Test + Code | **Fixed**: one engine per process; latest-reading query rewritten (219 ms to 1 ms on a year of data) and long histories averaged hourly; `python -m scripts.bench` shows every page query under 50 ms, so no read cache is needed |
| S-11 | Medium | Server | Device `001`, relay IDs and names hard-coded; four near-identical copy-pasted blocks | Code | **Fixed**: relays found by name everywhere (Control page, automation); IDs only in seed data; device from `DEVICE_ID` |
| S-12 | Medium | Web | Windows-only paths (`imagesavicon.png`, `help.md` vs `HELP.md`) break on Linux / Raspberry Pi | Code | **Fixed**: paths built from `__file__`; runs from any directory |
| S-13 | Medium | Server | Weather collector: no HTTP timeout, can double-fire or miss a slot | Code | **Fixed**: 10 s HTTP timeout, HTTP errors detected, one collection per 15-minute slot, one retry after 30 s |
| S-14 | Medium | Server | Background services are bare `while True` scripts with `print` logging and no supervision | Code | **Fixed**: `logging` everywhere; systemd units in `deploy/systemd/` restart each service 5 s after a crash; `deploy/install_services.py` installs them |
| S-15 | Medium | Web | Home and "Greenhouse Weather" (indoor data) pages are empty placeholders | Code | **Fixed**: Home shows controller status, reading freshness and relay states; Greenhouse Weather shows latest values and 24 h / 7 d / 30 d history |
| S-16 | Low | Repo | `requirements.txt` is UTF-16, pins 104 packages (Snowflake, boto3, Jupyter...), and `*.txt` is git-ignored | Code | **Fixed**: 6 runtime packages, plus `requirements-dev.txt` |
| S-17 | Low | Server | Mixed time zones: UTC for relay log and weather, local for Pico timestamps and watering schedule | Code | **Fixed**: UTC in storage and on the wire; only watering start times are local, by design |
| S-18 | Low | Web | App preferences live only in the browser session and defaults are duplicated on four pages | Code | **Fixed**: preferences saved in `app_preferences` and loaded by every new session; defaults in one place (`ui.py`) |
| S-19 | High | Server | Relay changes were logged even when the MQTT publish failed, so the log (and the dashboard) showed switches that never happened | Test | **Fixed**: events are logged only after the broker accepts the command; automation retries next pass |
| S-20 | Medium | Web | Remote Control accepted toggles while the controller was offline; the command was lost but the change was logged | Test | **Fixed**: toggles are disabled with a warning while the controller reports offline |
| P-14 | High | Pico | After a reboot all relays are off, but the server still showed (and automation assumed) their old states | Test | **Fixed**: every relay state is re-published when the MQTT link comes up; the server logs only real differences |
| P-15 | Critical | Pico/Server | Heater safety depended on the network: with Wi-Fi or the broker down, the server's "heater off" never arrived and the heater stayed as it was | Test | **Fixed**: the controller runs the rules itself after 2 min offline (local mode) and switches the heater off after 5 min without a temperature reading |
| R-01 | Low | Repo | `picoside/` committed with CRLF; any edit rewrites every line in the diff | Code | **Fixed**: `.gitattributes` stores text as LF (device files LF everywhere); repository renormalized |
| R-02 | Low | Repo | SQLite database files are committed alongside the code | Code | **Fixed**: database untracked and git-ignored; `python -m scripts.upgrade_db` creates and seeds a new one |
| R-03 | Low | Repo | No CI; tests did not exist before this review | n/a | **Fixed**: `.github/workflows/tests.yml` runs the full suite (Python 3.11, Ubuntu) on every push and pull request |

---

## Security

### SEC-01: Secrets committed to git (Critical)
- `picoside/config.json` contains the live Wi-Fi SSID and password.
- `server-streamlit/.env` and `.streamlit/secrets.toml` are tracked. They hold `SECRET_KEY`,
  `MQTT_USERNAME` and `MQTT_PASSWORD` fields.
- `picoside/mqtt_comm.py` had a second Wi-Fi SSID and password in a comment. This review removed
  the comment, but it is still in git history.

Removing the files from the latest commit does not help: they remain in history. **Rotate the Wi-Fi
password and any real secret values**, untrack the files, and ship `*.example` templates instead.
Rewriting history (`git filter-repo`) is optional and needs a force-push.

### SEC-02: MQTT is open (High)
The Pico's `MQTTClient` is created without user or password. `pico_functions.publish_relay_status`
ignores the `MQTT_USERNAME`/`MQTT_PASSWORD` values present in `.env`. Anything on the network can
publish relay commands once P-03 is fixed. Enable broker auth and ACLs; TLS is optional on a
trusted LAN.

### SEC-03: No web login (High)
Streamlit serves every page to anyone who can reach the port, including the heater and water
controls. Add authentication (Streamlit's built-in OIDC auth, or a reverse proxy with auth) before
exposing the app beyond the LAN.

---

## Pico firmware (`picoside/`)

### P-01: Boot crash once a broker is reachable (Critical, Test)
`MQTTComm.connect_mqtt()` calls `client.subscribe()`. The vendored `umqtt.simple.subscribe`
asserts that `set_callback()` was called, and nothing ever calls it. The resulting `AssertionError`
is not caught (only `OSError` is), so `main.py` dies at `mqtt = MQTTComm(config)`.

Today this is masked because `mqtt_broker` is still the placeholder `"YOUR_MQTT_BROKER"`, so the
connection fails first with `OSError`.
Test: `tests/picoside/test_firmware_mqtt.py::test_connects_to_reachable_broker_without_crashing`.

### P-02: Clock sync compounds the time-zone offset (Critical, Code)
`MicropyGPS(timezone_offset)` already returns local time. `compare_and_sync_time()` adds
`TIME_ZONE_OFFSET` again, so the GPS value it compares against is UTC-16 h. On a mismatch it calls
`adjust_time_zone()`, which shifts the RTC by the offset again. It never copies GPS time into the
RTC.
- At boot (RTC = UTC from NTP) the double error happens to leave the RTC on local time.
- The same check also runs at every local midnight (`main.py` loop). The comparison fails again
  and the RTC jumps back 8 h to 16:00. Eight hours later it reaches 00:00, and the jump repeats.
  **After the first night, the clock cycles 16:00→00:00 on the same date forever**, so every
  published timestamp is wrong.

Fix: keep the RTC in UTC and apply the offset only for display. Compare GPS UTC with RTC UTC, and on
drift set the RTC from GPS.

### P-03: Server commands never reach the relays (Critical, Code)
- The server publishes to `001/<relay_id>` with `{"device_id", "relay_id", "action_id"}`.
- The Pico subscribes to `greenhouse/control` and expects `{"relay": n}`.
- The Pico never polls: `mqtt.client.check_msg()` is commented out, and `subscribe_callback()` is
  never called.
- The Pico only supports *toggle*, while the server sends absolute on/off. A toggle can invert
  state if a message is lost.

The Remote Control page and the automation service therefore only write to the database. The
physical relays never move.

### P-04: Blocking in button handlers (Medium)
`show_ip` sleeps 10 s and `toggle_click` sleeps 100 ms inside the pin IRQ handlers. These are soft
IRQs on RP2040, so the whole main loop freezes, including sensor reads and MQTT. The handlers also
write to the LCD while the main loop may be mid-write on the same I2C bus. Fix: handlers only set a
flag or queue an event; the main loop does the work.

### P-05: No recovery from network loss (Medium)
`connect_wifi` blocks forever at boot if Wi-Fi is down. After boot, a dropped Wi-Fi link is never
re-established. `publish` retries MQTT once and then drops the reading. There is no watchdog, so a
hang needs a power cycle. Fix: `machine.WDT`, non-blocking reconnect with backoff, and a small
ring buffer of unsent readings.

### P-06: Local relay changes are invisible to the server (Medium)
Physical button toggles are not published, although `d_actions` already has codes 030/031
"Manual-…-From-Device". Relay state also resets to off on reboot. The server's view drifts from
reality, and the automation service (which only sends a command when it believes the state
differs) may never correct it.

### P-07: `ticks_ms` wrap-around (Medium)
`ticks_ms` wraps after about 12.4 days on MicroPython. `get_time_alive()` divides the raw value, so
uptime resets. `Buttons.relay_click` uses plain subtraction instead of `time.ticks_diff`, so
double-press detection can misfire at the wrap.

### P-08: Duplicate hardware initialisation (Low)
`utils`, `time_utils`, `gps_module` and `mqtt_comm` each call `load_config()` and create their own
`Display` (I2C bus plus LCD init) at import. `main.py` creates a sixth. This costs RAM and boot time
on a 264 KB device. Pass one `Display` in instead.

### P-09: Missing `global` (Low)
In `main.relay_control`, `last_relay_display_update = 0` creates a local variable. The relay screen
can take up to 1 s to show the new state.

### P-10: Uncalibrated light sensor (Low)
`read_ldr()` returns a raw 0–65535 ADC count. `relay_conditions.light_on_lumen = 3.0` cannot be
compared with it. Light automation needs calibration or a relative threshold.

### P-11: Button combos swapped; double press impossible (High, fixed)
Buttons use pull-ups, so a pressed button reads 0. `toggle_click` showed the IP address when
relay button 1 read **1** (not pressed). So a plain press of the screen button showed the IP, and
froze the loop for 10 s, while the combo cycled screens. The relay buttons were also debounced for
500 ms, the same as the double-press window, so a second press inside the window was always
discarded. Relays 5–8 could never be reached. Found while rewriting the loop.

### P-12: No readings for 5 minutes after boot (Medium, fixed)
`last_sensor_read_time` started at 0, and the first read waited until `ticks_ms()` passed
300 000. The LCD showed no temperature or humidity for the first 5 minutes after every reboot.

### P-13: Vendored MQTT client debug output (Low, fixed)
The vendored `umqtt.simple.wait_msg` printed the client and socket objects on every call. With
`check_msg()` in the main loop, that would have been 20 prints per second. The client also had no
socket timeout, so a silent broker could block the loop indefinitely.

### P-14: Relay state lost on reboot (High, fixed)
Relays start off at boot, but nothing told the server. The dashboard kept showing the old states,
and automation, believing the fan or heater was already on, never re-sent the command. The
controller now re-publishes all eight states whenever its MQTT link comes up. The ingest service
logs only states that differ from its record, so reconnects without a reboot add nothing.

### P-15: Heater safety depended on the network (Critical, fixed)
When readings stopped reaching the server, the server switched the heater off. But readings
usually stop because the controller's Wi-Fi or the broker is down, and then the "off" command
cannot reach the controller either. The heater stayed in its last state, possibly on, with
nothing watching it. Raised in review of the 15-minute stale-reading rule.

The fix puts the safety on the device:
- The controller keeps a copy of the automation settings (retained `settings` topic, saved to
  flash). After 2 minutes offline it runs the same rules itself ("local mode"), and a test checks
  its rules agree with the server's.
- The controller switches the heater off on its own if its sensor has given nothing for
  5 minutes, whatever the network is doing.
- While the controller reports offline, server automation stands back.

---

## Server and web app (`server-streamlit/`)

### S-01: Sensor data is never stored (Critical, Code + DB)
Nothing subscribes to `greenhouse/data` (the Pico's telemetry topic). `getgreenhousedata.py`
listens on `001/#`, which carries the server's own relay commands. The retired
`serverside/subs_from_pico.py` was the intended ingester, but its insert code was commented out.

`greenhouse_data` holds 12 rows, all from 20–22 Oct 2025. `greenhousecontrolauto.py` acts on the
latest row with no age check, so it would keep switching relays on readings months old.

### S-06: Automation loop defects (Critical, Code)
In `greenhousecontrolauto.py`:
1. **Heater commands go to the fan.** Both heater branches publish `relay_id="2"` but log
   `relayid "3"`.
2. **Fan logic conflicts.** Humidity and temperature are evaluated in two separate blocks against
   the same state snapshot, so one pass can publish *on* then *off*. The temperature block's off
   test compares temperature with the *humidity* threshold and buffer.
3. **Heater hysteresis is ignored.** The heater turns off as soon as the temperature reaches the
   trigger, so it will chatter around the setpoint.
4. **Busy loop.** When any input is missing the loop runs `continue` without `sleep`, which pins a
   CPU core and hammers the database.
5. **Manual overrides last at most 5 s.** There is no manual or auto mode, so the loop reverts any
   web or button toggle.
6. Watering windows use server local time and cannot cross midnight.
7. Every condition is re-read and re-parsed every 5 s through about 100 lines of copy-paste.

Fix by extracting a pure `decide(conditions, readings, states, now) -> actions` function and
unit-testing it table-style.

### S-02: Settings save breaks the automation service (High, Test)
`greenhousesettings.py` saves `str(st.time_input(...))`, which gives `"06:00:00"`.
`greenhousecontrolauto.py` parses with `strptime("%H:%M")` and `int(run_time[3:])`, so it raises
`ValueError` and the service exits.
Test: `test_pages.py::test_settings_save_keeps_hh_mm_time_format`.

### S-03: First toggle sends the wrong command (High, Test)
Each toggle's `args` are built *before* the widget exists in `session_state`, so on first render
`actionid` is always `"021"` (on). Switching a running fan off therefore publishes and logs "on".
`actiontime` is also fixed at render time rather than click time.
Test: `test_pages.py::test_control_first_toggle_off_sends_off`.

### S-04: Weather page crashes without two readings today (High, Test)
After filtering to today, the page calls `data.iloc[-1]` and `iloc[-2]`. This fails after local
midnight until two new readings arrive, and permanently if the collector stops (the case in the
committed database). Tests: `test_weather_page_handles_no_data_today` and
`test_weather_page_handles_single_reading_today`.

### S-05: North wind crashes the weather page (High, Test)
`wind_direction_descr[round(deg / 22.5)]` yields key 16 for 348.75–360°. Use
`conversions.degrees_to_compass_index`. Test: `test_weather_page_handles_north_wind`.

### S-07: Wrong unit conversions on the weather page (High, Code)
- `APPARENT_TEMPERATURE` is computed from the already-converted `TEMPERATURE` (°F→°F again), so it
  shows the wrong value, not just the wrong unit.
- US precipitation: `mm / 10 / 2.94` should be `mm / 25.4`, so values are about 14 % low.
- US snowfall: `cm / 2.94` should be `cm / 2.54`.

`conversions.py` has correct, tested helpers ready to use.

### S-08: Buffer units mislabelled (Medium)
Settings shows the fan and heater buffers with the °F label but never converts them. A buffer
entered as "2 °F" is stored as 2 °C (3.6 °F). Use `celsius_delta_to_fahrenheit` and its inverse.

### S-09: Empty-database crashes (Medium)
- `greenhousecontrol.load_page(None)` indexes `None`.
- `greenhousesettings.py` references `temperature_unit` and the `*_val` names that are only
  defined when data exists (`NameError`).

Show an empty state instead.

### S-10: Database access (Medium, Test + Code)
Every `local_utils` function calls `create_engine` and never disposes it. The test suite hit this:
pooled connections kept the SQLite file locked on Windows. `weather.py` and `weatherapp.py` repeat
the pattern.
- `relay_status` has no primary key or index, so "latest per relay" scans the whole growing log.
- `read_greenhouse_data` relies on SQLite's bare-column `GROUP BY` behaviour.

Use one engine (`st.cache_resource`), `st.cache_data(ttl=…)` for reads, and add indexes.

### S-11: Hard-coding and duplication (Medium)
Device `'001'`/`'picow1'` and relay IDs `1`–`4` are literals in SQL and UI code. The control page
repeats one ~35-line block per relay, the settings page and the automation service repeat blocks per
condition, and `lu.get_config()` plus `DB_CONN_STRING` are re-declared on several pages. A
multi-device setup needs these driven from `d_devices`/`d_relays`.

### S-12: Portability (Medium)
- `r"images\favicon.png"` appears on every page, and `help.py` opens `help.md` while the file is
  `HELP.md`. Both only work on Windows. A Raspberry Pi host would fail.
- All paths are relative to the working directory, so the app only works when launched from
  `server-streamlit/`.

Build paths from `Path(__file__).parent`.

### S-13: Weather collector timing (Medium)
- It polls every 10 s and fires when `minute % 15 == 0 and second <= 10`. It can fire twice in one
  window (the second insert fails on the primary key) or miss a slot if the sleep drifts.
- `requests.get` has no timeout, so one hung connection stops collection silently.

### S-14: Service management (Medium)
Three long-running scripts (`weatherapp.py`, `greenhousecontrolauto.py`, and a future ingester) are
started by hand. They log with `print` and nothing restarts them. Use `logging` and run them under
systemd, or as one supervised process.

### S-15: Placeholder pages (Medium)
`home.py` and `greenhouse.py` render only a title, so the core "what is happening in my greenhouse"
view does not exist yet. The retired Dash app had gauges and high/low history charts that could be
ported. They are in git history at `917594f:serverside/app_device_stats.py`.

### S-16: Dependencies (Low)
- `requirements.txt` is UTF-16 and pins 104 packages. Most are unrelated: Snowflake, boto3,
  IPython, Jupyter widgets, matplotlib, modin, black, and the conflicting `dotenv` package next to
  `python-dotenv`.
- The runtime needs about 7: streamlit, pandas, SQLAlchemy, paho-mqtt, python-dotenv, requests and
  pytz.
- `.gitignore` has `*.txt`, so new requirements files would be silently ignored.

### S-17: Time zones (Low)
The relay log and weather data are stored in UTC. The Pico publishes local time with no zone, and
that value is itself wrong because of P-02. The automation service uses local time for watering and
UTC for logging. Standardise on UTC in storage and on the wire.

### S-18: Preferences (Low)
Units, date and time formats live in `st.session_state` and reset when the browser session ends.
Defaults are re-declared on four pages. Centralise them in one helper, and persist them if needed.

### S-19: Unsent commands logged as done (High, fixed)
The Control page and the automation service logged a relay event whether or not
`publish_relay_command` succeeded. With the broker down, the dashboard showed a relay as switched,
and automation believed it and never retried. Found while reviewing the offline behaviour.

### S-20: Commands to an offline controller (Medium, fixed)
The device connects with a clean MQTT session, so commands sent while it is offline are dropped by
the broker. The page now reads `device_status` and disables the switches while the controller is
offline, saying that the controller's own safety rules are in charge.

---

## Repository

### R-01: Line endings (Low)
`picoside/*.py` blobs contain CRLF, while `core.autocrlf=true` stores LF for new edits. That is
why this review's diffs for picoside show every line changed. With whitespace ignored, the changes
are docstrings only. Add a `.gitattributes` (`* text=auto eol=lf`) and make one normalising commit.

### R-02: Databases in git (Low)
`server-streamlit/greenhouse.db` is tracked, so production data changes show up as binary diffs.
Keep `greenhouse.sql` plus a seed script in git, and back up the database separately.

### R-03: No CI (Low)
Run `pytest` on every push with a GitHub Actions workflow.

---

## Retired: `serverside/`
The Dash app was removed in this review because `server-streamlit/` replaced it. It was also
broken:
- `pub_to_pico.py` referenced an undefined `msg`.
- `subs_from_pico.py` declared two `PRIMARY KEY` columns and used the SQLAlchemy 1.x raw-string
  `execute`, and its inserts were commented out.
- Its schema (`SENSOR_DATA`, `SETTING_DATA`, …) differs from the current normalised schema.

What was kept:
- `conversions.py` was ported to `server-streamlit/conversions.py`. It now returns floats instead
  of rounded ints, and adds delta and compass helpers.
- Ideas, now listed in the plan: gauge and history charts for the indoor dashboard (S-15), and an
  MQTT subscriber that writes telemetry to the database (S-01).

The full code remains available in git history (`git show 917594f:serverside/<file>`).
