"""
Compile every device file with ``mpy-cross``, MicroPython's own compiler.

The other firmware tests run on CPython, which accepts syntax MicroPython does
not; this catches that. Skipped when ``mpy-cross`` is not installed
(``pip install -r requirements-dev.txt``).
"""
import subprocess
import sys

import pytest

from support import PICO_DIR

mpy_cross = pytest.importorskip("mpy_cross")

DEVICE_FILES = sorted(PICO_DIR.rglob("*.py"))


@pytest.mark.parametrize("path", DEVICE_FILES, ids=lambda p: p.relative_to(PICO_DIR).as_posix())
def test_compiles_for_micropython(path, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "mpy_cross", "-o", str(tmp_path / "out.mpy"), str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
