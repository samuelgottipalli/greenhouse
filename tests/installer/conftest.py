"""Make the ``installer`` package importable (it lives at the repository root)."""
import sys

import pytest

from support import REPO_ROOT

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def env_files(tmp_path, monkeypatch):
    """Point the installer at a throwaway ``server/.env``."""
    from installer import steps

    env = tmp_path / ".env"
    monkeypatch.setattr(steps, "ENV_FILE", env)
    return env
