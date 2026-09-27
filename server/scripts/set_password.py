"""
Set (or change) the dashboard password.

Usage (from the ``server/`` folder)::

    python -m scripts.set_password

Asks for the password twice and writes its hash to ``APP_PASSWORD_HASH`` in
``server/.env`` (creating the file if needed, keeping every other line).
Restart the dashboard afterwards. To remove the password, delete that line.
"""
import getpass
import sys
from pathlib import Path

from core.auth import hash_password
from core.settings import ENV_FILE

MIN_LENGTH = 8
KEY = "APP_PASSWORD_HASH"


def write_hash(env_file: Path, password_hash: str) -> None:
    """
    Put ``APP_PASSWORD_HASH=<hash>`` into an env file, replacing any old value.

    Args:
        env_file (Path): ``.env`` file (created if missing).
        password_hash (str): Output of ``core.auth.hash_password``.
    """
    lines = env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    lines = [line for line in lines if not line.strip().startswith(f"{KEY}=")]
    lines.append(f"{KEY}={password_hash}")
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(env_file: Path = ENV_FILE, ask=getpass.getpass) -> int:
    """
    Prompt for the new password and save its hash.

    Args:
        env_file (Path): ``.env`` file to update.
        ask (callable): Prompt function (injected in tests).

    Returns:
        int: Process exit code.
    """
    password = ask("New dashboard password: ")
    if len(password) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters.", file=sys.stderr)
        return 1
    if ask("Repeat it: ") != password:
        print("The passwords do not match.", file=sys.stderr)
        return 1
    write_hash(env_file, hash_password(password))
    print(f"Saved to {env_file}. Restart the dashboard to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
