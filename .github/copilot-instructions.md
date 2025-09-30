## Greenhouse Project AI Agent Guidelines

This project consists of two main components: `picoside` (MicroPython device) and `serverside` (Python Dash web application).

### 1. Architecture Overview

*   **Picoside**: An ESP32-based MicroPython device responsible for sensor readings (DHT, LDR), relay control, GPS data acquisition, LCD display management, and MQTT communication. The core logic resides in `picoside/main.py`.
*   **Serverside**: A Python Dash web application providing a "Control Center" for monitoring and managing the greenhouse. It displays an overview, device information, and weather conditions. The main application entry point is `serverside/app.py`.

### 2. Data Flow and Communication

*   **Picoside to Serverside**: Sensor data, GPS data, and relay statuses are published by the Pico to an MQTT broker via `picoside/mqtt_comm.py`.
*   **Serverside to Picoside**: Commands and settings can be sent from the Dash application to the Pico via MQTT using `serverside/pub_to_pico.py`.
*   **Data Storage**: `serverside/subs_from_pico.py` subscribes to MQTT topics and stores incoming data into the `serverside/greenhouse.db` SQLite database.
*   **Web Application Data Retrieval**: The Dash application queries `serverside/greenhouse.db` to display information. External weather data is fetched via `serverside/weather_api.py`.

### 3. Key Files and Directories

*   **`picoside/main.py`**: Main MicroPython application logic.
*   **`picoside/config.json`**: Device-specific configuration for the Pico.
*   **`serverside/app.py`**: Main Dash web application entry point.
*   **`serverside/greenhouse.db`**: SQLite database for storing application data.
*   **`serverside/app_*.py`**: Modules within `serverside` that define different sections/tabs of the Dash dashboard (e.g., `app_overview.py`, `app_device_info.py`, `app_weather.py`).

### 4. Developer Workflows

*   **Picoside Development**: Requires a MicroPython development environment. Code is typically flashed to the ESP32 device. Refer to MicroPython documentation for flashing procedures.
*   **Serverside Development**: Run the Dash application using `python serverside/app.py`. The application will be accessible via a web browser, usually at `localhost:8050`.
*   **Database Interaction**: The `greenhouse.db` is a SQLite database. You can use standard SQLite tools for inspection and debugging.

### 5. Project-Specific Conventions

*   **Configuration**: Pico device settings are managed in `picoside/config.json`.
*   **MQTT**: All inter-component communication relies heavily on MQTT. Understand the topics and message formats used.
*   **Dash UI**: The Dash application uses `dash-bootstrap-components` for styling and includes client-side callbacks for theme and unit switching.
