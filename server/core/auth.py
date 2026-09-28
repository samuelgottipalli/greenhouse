"""
Password hashing for the dashboard login.

The password is never stored. ``server/.env`` holds ``APP_PASSWORD_HASH`` in
the form ``pbkdf2_sha256:<iterations>:<salt hex>:<hash hex>`` (colons rather
than ``$`` so ``.env`` variable expansion leaves it alone). Create it with
``python -m scripts.set_password``.

"Keep me logged in" uses a signed token in a browser cookie:
``<expiry unix time>.<HMAC-SHA256>``. The HMAC key is derived from the stored
password hash, so changing the password signs every browser out.
"""
import hashlib
import hmac
import secrets
import time

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
REMEMBER_DAYS = 30


def _token_key(password_hash: str) -> bytes:
    """Derive the cookie-signing key from the stored password hash."""
    return hashlib.sha256(("greenhouse-login:" + password_hash).encode("utf-8")).digest()


def make_login_token(password_hash: str, days: int = REMEMBER_DAYS, now: float | None = None) -> str:
    """
    Make a token that proves a successful login until it expires.

    Args:
        password_hash (str): ``APP_PASSWORD_HASH``.
        days (int): How long it stays valid.
        now (float | None): Unix time now (for tests).

    Returns:
        str: ``<expiry>.<signature>``.
    """
    expiry = str(int((time.time() if now is None else now) + days * 86400))
    signature = hmac.new(_token_key(password_hash), expiry.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{expiry}.{signature}"


def login_token_valid(token: str | None, password_hash: str, now: float | None = None) -> bool:
    """
    Check a token from :func:`make_login_token`.

    Args:
        token (str | None): Cookie value.
        password_hash (str): ``APP_PASSWORD_HASH`` (a different one invalidates it).
        now (float | None): Unix time now (for tests).

    Returns:
        bool: True if it is signed with this password and not expired.
    """
    if not token or "." not in token:
        return False
    expiry, _, signature = token.partition(".")
    if not expiry.isdigit():
        return False
    expected = hmac.new(_token_key(password_hash), expiry.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    return int(expiry) > (time.time() if now is None else now)


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
