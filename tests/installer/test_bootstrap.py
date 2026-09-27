"""
The double-click starters: setup.bat (Windows) and setup.sh (macOS, Linux).
They make venv/, install installer/requirements.txt and open the installer.
"""
from support import REPO_ROOT

BAT = (REPO_ROOT / "setup.bat").read_bytes()
SH = (REPO_ROOT / "setup.sh").read_bytes()


def test_bat_uses_crlf_and_starts_the_installer():
    assert b"\r\n" in BAT and b"\n" not in BAT.replace(b"\r\n", b"")
    text = BAT.decode("utf-8")
    assert "venv\\Scripts\\python.exe" in text and "installer\\requirements.txt" in text
    assert "-m installer" in text and "winget install -e --id Python.Python.3.12" in text


def test_sh_uses_lf_and_starts_the_installer():
    assert b"\r" not in SH and SH.startswith(b"#!/bin/sh\n")
    text = SH.decode("utf-8")
    assert "python3 -m venv venv" in text and "installer/requirements.txt" in text
    assert "exec venv/bin/python -m installer" in text


def test_installer_requirements_include_the_server():
    lines = (REPO_ROOT / "installer" / "requirements.txt").read_text(encoding="utf-8").splitlines()
    assert "-r ../server/requirements.txt" in lines
    assert any(line.startswith("PySide6-Essentials==") for line in lines)
    assert any(line.startswith("mpremote==") for line in lines)
