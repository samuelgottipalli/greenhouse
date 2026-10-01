# What's new

Each release lists what changed for the server (dashboard, services and installer) and for the
controller (the Pico W). Versions read *major.minor.patch*: *major* goes up for big changes that
need care when upgrading, *minor* for new features and *patch* for fixes only. A version ending in
`-dev` is still being built.

## Server 1.4.0-dev · Controller 1.4.0-dev (in progress)

Being built on the `develop` branch.

- **Cloud MQTT services.** Use a hosted MQTT service (for example HiveMQ Cloud's free plan)
  instead of running Mosquitto yourself: a new choice in the installer, encrypted connections
  (TLS) from the server and the controllers, and the controller checks the service's certificate.
  The setup code and the controller's setup page know about encrypted services.

## Server 1.3.0 · Controller 1.3.0 (2026-09-30)

- **Restart buttons** on the new Settings › System tab: restart the controller, the dashboard and
  background services, or the server computer. Each asks first.
- The controller understands the restart command (update it to 1.3.0 for its button to work).
- The service installer adds a permission that lets the dashboard run exactly those two restart
  commands on the server, and nothing else.

## Server 1.2.0 · Controller 1.1.1 (2026-09-29)

The controller is unchanged; only the server is updated.

- **Any period in the reports.** Both Reports tabs offer 24 hours, 7 days, 30 days or a date range
  within the last 6 months; long periods show hourly or daily averages.
- **Outdoor weather history**: temperature, humidity, rain and wind over the chosen period, with
  highs, lows and a table.
- **Analysis page**: each month of the last year as a box plot (middle 95 %, middle half, median,
  average), with this month so far next to the same month last year.
- **Monthly summaries and clean-up.** Readings are kept in full for 6 months. On the 1st (or at
  the next start, if the server was off) each finished month is summarised for the Analysis page,
  the database is backed up, and readings older than 6 months are deleted. This replaces the
  nightly hourly averaging.

## Server 1.1.1 · Controller 1.1.1 (2026-09-28)

- **Free memory is reported correctly.** The controller clears out unused memory before measuring,
  so the Home page shows the real figure (about 140 KB) instead of a low, jumpy one.

## Server 1.1.0 · Controller 1.1.0 (2026-09-28)

- **Version numbers you can read.** The dashboard (menu, Help › About, Settings › Controllers),
  the controller's screen and the installer show versions like 1.1.0, and updates say which
  version they came from ("Updated from 1.0.0 to 1.1.0").
- **Updates from 1.0.0** work over Wi-Fi as before; a controller set up by hand is compared by
  version name.
- **Choose the location on the dashboard** (Settings › Location): find a town or type the
  latitude and longitude. The outdoor weather and the sunrise and sunset times (for the grow
  light) switch to it straight away, without restarting anything.

## Server 1.0.0 · Controller 1.0.0 (2026-09-28)

The first complete version.

- **Dashboard:** Home (health at a glance), Reports (greenhouse and outdoor weather with gauges
  and charts), Remote Control, Settings (display, greenhouse rules, controllers) and Help.
- **Controller:** reads temperature, humidity and light; runs the fan, heater, grow light and
  watering; keeps running your rules on its own when the network or server is down.
- **Setup:** a desktop installer for the server, a phone setup hotspot for the controller,
  and software updates for the controller over Wi-Fi with automatic roll-back.
- **Alerts** on the dashboard, and optionally to your phone or by email.
