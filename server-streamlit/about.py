"""
About the Greenhouse Control System
"""
import streamlit as st

st.set_page_config(
    page_title="About",
    page_icon=r"images\favicon.png",
    layout="centered",
)
st.logo(r"images\favicon.png", icon_image=r"images\favicon.png", size="large")

about = """
# About the Greenhouse Control System

This project is a comprehensive IoT solution for monitoring and controlling a greenhouse environment. It leverages a Raspberry Pi Pico microcontroller for on-site hardware management and a Streamlit web application for remote monitoring and control.

## System Architecture

The system is composed of three main parts:

1.  **`picoside` (Microcontroller Unit):**
    *   This is the firmware running on a Raspberry Pi Pico located inside the greenhouse.
    *   It interfaces directly with various sensors (e.g., temperature, humidity, soil moisture) and actuators (e.g., relays for fans, pumps, lights).
    *   It gathers data, executes control commands, and communicates with the server via the MQTT protocol.
    *   Includes modules for GPS (`gps_module.py`) and direct hardware control (`buttons.py`, `relays.py`, `sensors.py`).

2.  **`serverside` (Backend Logic):**
    *   This component acts as the central hub for data and communication.
    *   It includes an MQTT subscriber (`subs_from_pico.py`) to receive and log data from the Pico into a database (`greenhouse.db`).
    *   It also contains logic to publish commands back to the Pico (`pub_to_pico.py`).
    *   This layer processes and stores all historical data for analysis and display.

3.  **`server-streamlit` (Web Dashboard):**
    *   This is the user-facing web application built with Streamlit.
    *   It provides a user-friendly interface to:
        *   View real-time and historical sensor data.
        *   Check local weather information (`weather.py`).
        *   Manually trigger relays to control greenhouse equipment (`greenhousecontrol.py`).
        *   Adjust system settings (`greenhousesettings.py`).
        *   View device status and statistics.

## Technology Stack

*   **Hardware:** Raspberry Pi Pico
*   **Microcontroller Programming:** MicroPython
*   **Communication Protocol:** MQTT
*   **Backend & Web App:** Python
*   **Web Framework:** Streamlit
*   **Database:** SQLite
"""

st.markdown(about)
