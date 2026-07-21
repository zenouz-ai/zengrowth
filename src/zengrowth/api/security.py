"""Operator auth primitives: PBKDF2 password hashing + HMAC-signed session cookie.

Single-operator app, so there is no user table: the password hash and the
session-signing secret live in the environment (ZENGROWTH_OPERATOR_PASSWORD_HASH,
ZENGROWTH_SESSION_SECRET). Everything here is stdlib-only.

Generate a password hash for .env with:

    python -m zengrowth.api.security hash 'your-password'
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sys
import time

_PBKDF2_ALGO = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 600_000


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# --- Password hashing -------------------------------------------------------


def hash_password(raw: str, *, iterations: int = _DEFAULT_ITERATIONS) -> str:
    """Return ``pbkdf2_sha256$iterations$salt$hash`` for storage in .env."""
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, iterations)
    return f"{_PBKDF2_ALGO}${iterations}${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(raw: str, stored_hash: str) -> bool:
    """Constant-time verify ``raw`` against a stored PBKDF2 hash."""
    try:
        algo, iter_str, salt_b64, hash_b64 = stored_hash.split("$")
        if algo != _PBKDF2_ALGO:
            return False
        iterations = int(iter_str)
        salt = _b64decode(salt_b64)
        expected = _b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    derived = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


# --- Session cookie ---------------------------------------------------------


def _sign(secret: str, payload_b64: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(sig)


def make_session_cookie(secret: str, *, ttl_seconds: int, issued_at: int | None = None) -> str:
    """Return a signed ``<payload>.<signature>`` cookie value."""
    iat = int(issued_at if issued_at is not None else time.time())
    payload = {"iat": iat, "exp": iat + int(ttl_seconds)}
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(secret, payload_b64)}"


def verify_session_cookie(secret: str, value: str, *, now: int | None = None) -> bool:
    """True if the cookie signature is valid and the session has not expired."""
    try:
        payload_b64, signature = value.split(".")
    except (ValueError, AttributeError):
        return False
    if not hmac.compare_digest(signature, _sign(secret, payload_b64)):
        return False
    try:
        payload = json.loads(_b64decode(payload_b64))
        exp = int(payload["exp"])
    except (ValueError, TypeError, KeyError):
        return False
    return int(now if now is not None else time.time()) < exp


def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "hash":
        print("usage: python -m zengrowth.api.security hash '<password>'", file=sys.stderr)
        return 2
    print(hash_password(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
