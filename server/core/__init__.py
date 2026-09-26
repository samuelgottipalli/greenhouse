"""
Shared, UI-independent code for the greenhouse server.

* ``settings``: configuration from ``server/.env``.
* ``db``: all database reads and writes.
* ``migrations``: create or upgrade the database schema.
* ``mqtt``: messages to the greenhouse controller.
* ``weather_api``: Open-Meteo client.
* ``conversions`` / ``timeutil`` / ``weather_codes``: pure helpers.
"""
