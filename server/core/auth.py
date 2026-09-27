"""
Password hashing for the dashboard login.

The password is never stored. ``server/.env`` holds ``APP_PASSWORD_HASH`` in
the form ``pbkdf2_sha256:<iterations>:<salt hex>:<hash hex>`` (colons rather
than ``$`` so ``.env`` variable expansion leaves it alone). Create it with
``python -m scripts.set_password``.
"""
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    """
    Hash a password for storage.

    Args:
        password (str): Plain-text password.
        salt (bytes | None): 16 random bytes; generated when not given.
        iterations (int): PBKDF2 rounds.

    Returns:
        str: ``pbkdf2_sha256:<iterations>:<salt hex>:<hash hex>``.
    """
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}:{iterations}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """
    Check a password against a stored hash in constant time.

    Args:
        password (str): Password typed by the user.
        stored (str): Value produced by :func:`hash_password`.

    Returns:
        bool: True if it matches; False for a wrong password or a malformed hash.
    """
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split(":")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)
