#!/bin/sh
# Greenhouse setup for macOS and Linux: run `sh setup.sh` in this folder.
# Makes a Python environment in venv/, installs the installer's packages, and opens it.
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is not installed."
    echo "  macOS:    install it from https://www.python.org/downloads/"
    echo "  Linux:    sudo apt install python3 python3-venv"
    exit 1
fi
if [ ! -x venv/bin/python ]; then
    echo "Creating the Python environment..."
    python3 -m venv venv || { echo "On Debian/Ubuntu/Raspberry Pi OS first run: sudo apt install python3-venv"; exit 1; }
fi
echo "Installing the installer (first time: a few minutes)..."
venv/bin/python -m pip install --disable-pip-version-check -q -r installer/requirements.txt
exec venv/bin/python -m installer
