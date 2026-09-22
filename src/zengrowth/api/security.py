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


def make_session_cookie(
    secret: str,
    *,
    ttl_seconds: int,
    issued_at: int | None = None,
    session_id: str | None = None,
) -> str:
    """Return a signed ``<payload>.<signature>`` cookie value.

    Payload is ``iat`` / ``exp`` plus a server-side ``sid`` (SEC-03). The sid is
    what logout revokes; HMAC alone is not enough to kill a stolen cookie.
    """
    iat = int(issued_at if issued_at is not None else time.time())
    sid = session_id or secrets.token_urlsafe(32)
    payload = {"iat": iat, "exp": iat + int(ttl_seconds), "sid": sid}
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(secret, payload_b64)}"


def parse_session_cookie(secret: str, value: str, *, now: int | None = None) -> dict | None:
    """Return the cookie payload if the signature is valid, it has not expired,
    and a session id is present. Otherwise ``None``.
    """
    try:
        payload_b64, signature = value.split(".")
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(signature, _sign(secret, payload_b64)):
        return None
    try:
        payload = json.loads(_b64decode(payload_b64))
        exp = int(payload["exp"])
        sid = payload.get("sid")
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(sid, str) or not sid.strip():
        return None
    if int(now if now is not None else time.time()) >= exp:
        return None
    return payload


def verify_session_cookie(secret: str, value: str, *, now: int | None = None) -> bool:
    """True if the cookie signature is valid, ``sid`` is present, and it has not expired.

    Does not check the server-side allowlist — use ``is_live_session_cookie``.
    """
    return parse_session_cookie(secret, value, now=now) is not None


def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "hash":
        print("usage: python -m zengrowth.api.security hash '<password>'", file=sys.stderr)
        return 2
    print(hash_password(argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
