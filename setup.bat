@echo off
rem Greenhouse setup for Windows: double-click this file.
rem Makes a Python environment in venv\, installs the installer's packages, and opens it.
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Installing it now; approve the prompt, then run setup.bat again.
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  pause
  exit /b 1
)
if not exist "venv\Scripts\python.exe" (
  echo Creating the Python environment...
  py -3 -m venv venv || goto :failed
)
echo Installing the installer (first time: a few minutes)...
"venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r installer\requirements.txt || goto :failed
start "" "venv\Scripts\pythonw.exe" -m installer
exit /b 0
:failed
echo Setup could not start. Check the internet connection and try again.
pause
exit /b 1
