"""Encrypted-at-rest storage for operator-managed secrets (the LLM API key).

A first-time user must be able to add an API key from the dashboard, not only via
``.env`` (PS-P1). Keys are persisted in the ``AppSecret`` table, encrypted with a
stdlib encrypt-then-MAC stream cipher (HMAC-SHA256 in counter mode, then an
HMAC-SHA256 tag) keyed by a 32-byte master key kept in ``data/.keyring`` (mode
0600, outside the DB and gitignored). This matches the stdlib-only house style of
``api/security.py`` and avoids a new crypto dependency, while keeping the key out
of plaintext so a leaked DB snapshot alone does not expose the credential.

Environment variables remain the source of truth; this is the fallback the API
loads on boot and updates at runtime when the operator saves a key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from pathlib import Path

from sqlmodel import Session, select

from .config import Settings, get_settings
from .models import AppSecret

_NONCE_BYTES = 16
_TAG_BYTES = 32
_MASTER_BYTES = 32
_KEYRING_FILENAME = ".keyring"

# Provider name -> the Settings attribute the loaded value populates.
SECRET_PROVIDERS: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "tavily": "tavily_api_key",
    "openai": "openai_api_key",
}


def _keyring_path(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    # Co-locate with the SQLite DB under data/ when possible; fall back to data/.
    db = settings.database_url
    prefix = "sqlite:///"
    base = Path(db[len(prefix):]).parent if db.startswith(prefix) else Path("data")
    return base / _KEYRING_FILENAME


def _master_key(settings: Settings | None = None) -> bytes:
    """Return the 32-byte master key, generating and persisting it on first use."""
    path = _keyring_path(settings)
    if path.exists():
        raw = path.read_bytes().strip()
        try:
            key = base64.urlsafe_b64decode(raw)
        except (ValueError, TypeError):
            key = b""
        if len(key) == _MASTER_BYTES:
            return key
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(_MASTER_BYTES)
    # Write 0600 so other local users can't read the master key.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(base64.urlsafe_b64encode(key))
    return key


def _keystream(master: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(master, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: str, *, settings: Settings | None = None) -> str:
    master = _master_key(settings)
    data = plaintext.encode("utf-8")
    nonce = secrets.token_bytes(_NONCE_BYTES)
    ciphertext = bytes(b ^ k for b, k in zip(data, _keystream(master, nonce, len(data)), strict=False))
    tag = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")


def decrypt(token: str, *, settings: Settings | None = None) -> str | None:
    """Return the plaintext, or ``None`` if the token is malformed or tampered."""
    master = _master_key(settings)
    try:
        blob = base64.urlsafe_b64decode(token.encode("ascii"))
    except (ValueError, TypeError):
        return None
    if len(blob) < _NONCE_BYTES + _TAG_BYTES:
        return None
    nonce = blob[:_NONCE_BYTES]
    tag = blob[_NONCE_BYTES : _NONCE_BYTES + _TAG_BYTES]
    ciphertext = blob[_NONCE_BYTES + _TAG_BYTES :]
    expected = hmac.new(master, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        return None
    plaintext = bytes(b ^ k for b, k in zip(ciphertext, _keystream(master, nonce, len(ciphertext)), strict=False))
    return plaintext.decode("utf-8", errors="replace")


# --- AppSecret CRUD ---------------------------------------------------------


def get_secret(session: Session, name: str, *, settings: Settings | None = None) -> str | None:
    row = session.get(AppSecret, name)
    if row is None:
        return None
    return decrypt(row.ciphertext, settings=settings)


def set_secret(session: Session, name: str, value: str, *, settings: Settings | None = None) -> None:
    ciphertext = encrypt(value, settings=settings)
    row = session.get(AppSecret, name)
    if row is None:
        session.add(AppSecret(name=name, ciphertext=ciphertext))
    else:
        row.ciphertext = ciphertext
        session.add(row)
    session.commit()


def delete_secret(session: Session, name: str) -> bool:
    row = session.get(AppSecret, name)
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


def list_secret_names(session: Session) -> set[str]:
    return set(session.exec(select(AppSecret.name)).all())


def load_secrets_into_settings(session: Session, settings: Settings | None = None) -> list[str]:
    """Populate unset ``Settings`` keys from stored secrets. Env always wins.

    Returns the provider names loaded from storage (for logging). Called on boot so
    a key saved in the dashboard survives a restart, and mutating the cached
    ``Settings`` singleton means every later LLM client picks it up with no restart.
    """
    settings = settings or get_settings()
    stored = list_secret_names(session)
    loaded: list[str] = []
    for provider, attr in SECRET_PROVIDERS.items():
        if getattr(settings, attr):
            continue  # env / already-set value wins
        if provider not in stored:
            continue
        value = get_secret(session, provider, settings=settings)
        if value:
            setattr(settings, attr, value)
            loaded.append(provider)
    return loaded
