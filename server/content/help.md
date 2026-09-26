# Greenhouse Control System Help

This guide explains how to use the Greenhouse Control System web app.

## Navigation

Pick a page from the sidebar on the left.

### Home

The landing page. A system status summary is planned for this page.

### Reports › Weather Data

*   Shows today's outdoor weather: temperature, humidity, conditions, precipitation, wind,
    sunrise and sunset.
*   Each card shows the change since the previous reading and a small chart for the day.
*   Refreshes automatically every 15 minutes.

### Reports › Greenhouse Weather

Indoor sensor readings from the greenhouse controller. This page is not built yet.

### Control › Remote Control

*   One switch per device: **Fan**, **Heater**, **Light** and **Water**.
*   Flip a switch to turn that device on or off. The badge next to it shows the last recorded
    state.
*   The automation service may change a device again based on your Greenhouse Settings.

### Settings › App Settings

Choose how the app displays information:

*   **Display Units:** SI (°C, km/h, cm) or US (°F, mph, in).
*   **Date Format** and **Time Format** (12- or 24-hour).
*   **Timezone:** UTC, or a local time zone.

These choices apply to your current browser session.

### Settings › Greenhouse Settings

Set the rules the automation service follows:

*   **Fan:** the temperature and humidity at which the fan turns on. The **Buffer** is how far
    the value must fall before the fan turns off again. This stops the fan switching on and off
    rapidly.
*   **Heater:** the temperature below which the heater turns on, with its own buffer.
*   **Water:** up to four daily start times, each with a run time in minutes. Set the run time to 0 to turn a slot off.

Buttons:

*   **Save** stores your changes.
*   **Revert** puts back the last saved settings.
*   **Restore Defaults** puts back the factory settings.

## Frequently Asked Questions (FAQ)

**Q: The weather data is not updating. What should I do?**

1.  Make sure the weather collector (`python -m services.weather_collector`) is running on the server.
2.  Check that the server has internet access.

**Q: A device did not respond to the switch. What should I do?**

1.  **Check the Pico:** make sure the controller is powered on and connected to Wi-Fi. Press
    button 1 and the screen button together to show its IP address.
2.  **Check MQTT:** make sure the MQTT broker is running, and that the controller and the server
    are configured with the same broker address.

**Q: How do I change what a relay controls?**

This needs a wiring change in the greenhouse. Relays 1-4 are water, fan, heater and light. These
names are currently fixed in the app, so keep the wiring to match.
