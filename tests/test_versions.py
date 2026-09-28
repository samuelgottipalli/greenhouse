"""Version numbers (Phase 6): both are valid and CHANGELOG.md describes them."""
import re

from support import PICO_DIR, REPO_ROOT, SERVER_DIR

SEMVER = re.compile(r"^\d+\.\d+\.\d+(-dev)?$")


def version_in(path):
    found = re.search(r'^VERSION = "([^"]+)"$', path.read_text(encoding="utf-8"), re.M)
    assert found, path
    return found.group(1)


def test_versions_are_major_minor_patch():
    for path in (SERVER_DIR / "version.py", PICO_DIR / "version.py"):
        assert SEMVER.match(version_in(path)), path


def test_changelog_has_an_entry_for_each_version():
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [line for line in changelog.splitlines() if line.startswith("## ")]
    assert f"Server {version_in(SERVER_DIR / 'version.py')}" in headings[0]
    assert f"Controller {version_in(PICO_DIR / 'version.py')}" in headings[0]


def test_controller_reads_the_same_version_as_the_server_offers():
    import importlib
    import sys

    sys.path.insert(0, str(PICO_DIR))
    try:
        ota = importlib.import_module("ota")
        from core import firmware

        assert ota.version_name(str(PICO_DIR / "version.py")) == firmware.available_name()
    finally:
        sys.path.remove(str(PICO_DIR))
        sys.modules.pop("ota", None)
