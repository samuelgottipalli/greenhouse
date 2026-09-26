"""Repository-wide checks that are easy to break by accident."""
import subprocess

import pytest

from support import REPO_ROOT

TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".json", ".sql", ".yml", ".yaml", ".ini", ".example", ".service", ".conf", ".acl"}


def tracked_files() -> list[str]:
    result = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return result.stdout.split()


def test_text_files_are_utf8():
    # pip on Linux cannot read the UTF-16 requirements.txt that once broke CI.
    bad = []
    for name in tracked_files():
        path = REPO_ROOT / name
        if path.suffix in TEXT_SUFFIXES or path.name.startswith(".env"):
            raw = path.read_bytes()
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                bad.append(name)
                continue
            if b"\x00" in raw:
                bad.append(name)
    assert bad == []


@pytest.mark.parametrize("secret", ["server/.env", "picoside/device/config.json", "server/data/greenhouse.db"])
def test_secrets_and_data_are_not_tracked(secret):
    assert secret not in tracked_files()
