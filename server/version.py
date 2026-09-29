"""
The server's version (dashboard, services, installer).

Versions read ``major.minor.patch``: *major* goes up for big changes that
need care when upgrading, *minor* for new features, *patch* for fixes only.
A version still being built on the ``develop`` branch ends in ``-dev``.
What changed in each release is in ``CHANGELOG.md``; released versions are
tagged ``v<version>`` on ``main``. The controller has its own version in
``picoside/device/version.py``.
"""

VERSION = "1.2.0"
