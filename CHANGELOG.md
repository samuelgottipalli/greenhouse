# What's new

Each release lists what changed for the server (dashboard, services and installer) and for the
controller (the Pico W). Versions read *major.minor.patch*: *major* goes up for big changes that
need care when upgrading, *minor* for new features and *patch* for fixes only. A version ending in
`-dev` is still being built.

## Server 1.1.0-dev · Controller 1.1.0-dev (in progress)

Being built on the `develop` branch.

- **Version numbers you can read.** The dashboard, the controller's screen and the installer show
  versions like 1.1.0, and updates say which version they came from.
- **Cloud MQTT services.** Use a hosted MQTT service (for example HiveMQ Cloud) instead of running
  Mosquitto yourself, with encrypted, verified connections from the server and the controllers.

## Server 1.0.0 · Controller 1.0.0 (2026-09-28)

The first complete version.

- **Dashboard:** Home (health at a glance), Reports (greenhouse and outdoor weather with gauges
  and charts), Remote Control, Settings (display, greenhouse rules, controllers) and Help.
- **Controller:** reads temperature, humidity and light; runs the fan, heater, grow light and
  watering; keeps running your rules on its own when the network or server is down.
- **Setup:** a desktop installer for the server, a phone setup hotspot for the controller,
  and software updates for the controller over Wi-Fi with automatic roll-back.
- **Alerts** on the dashboard, and optionally to your phone or by email.
