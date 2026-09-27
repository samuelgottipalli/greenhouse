# About the Greenhouse Control System

This project monitors and controls a greenhouse. A Raspberry Pi Pico W inside the greenhouse reads
the sensors and switches the equipment. This Streamlit web app lets you watch conditions, set the
automation rules and switch devices by hand from anywhere on the home network.

## System Architecture

The system has two parts that exchange messages through an MQTT broker.

1.  **`picoside/device` (greenhouse controller):**
    *   MicroPython firmware running on a Raspberry Pi Pico W.
    *   Reads a DHT22 temperature/humidity sensor and a light sensor (LDR), and keeps time from the internet (NTP).
    *   Drives an 8-channel relay board (water, fan, heater, light and four spares).
    *   Shows readings on a 20x4 LCD. Five buttons toggle relays without the web app.
    *   Publishes readings over MQTT every 5 minutes.

2.  **`server` (web app and background services):**
    *   **Web app** (`app.py`): the pages in the sidebar, for weather reports, remote
        control and settings.
    *   **Automation service** (`services/automation.py`): applies the fan, heater and watering
        rules from *Greenhouse Settings* and sends relay commands.
    *   **Ingest service** (`services/ingest.py`): stores the controller's readings, relay changes
        and online/offline status.
    *   **Weather collector** (`services/weather_collector.py`): stores outdoor weather from Open-Meteo every
        15 minutes.
    *   **Database** (`data/greenhouse.db`, SQLite): settings, sensor readings, relay history and
        weather.

## Technology Stack

*   **Hardware:** Raspberry Pi Pico W, DHT22, LDR, 20x4 I2C LCD, 8-channel relay board
*   **Firmware:** MicroPython
*   **Communication:** MQTT
*   **Web app and services:** Python, Streamlit, pandas, SQLAlchemy
*   **Database:** SQLite
*   **Weather data:** Open-Meteo API
