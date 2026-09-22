"""Operator auth endpoints: login (set signed cookie), logout, session check."""

from __future__ import annotations

import hmac
import ipaddress
import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ...config import get_settings
from ..operator_sessions import (
    create_operator_session,
    is_live_session_cookie,
    revoke_operator_session,
)
from ..security import make_session_cookie, parse_session_cookie, verify_password

router = APIRouter(tags=["auth"])

SESSION_COOKIE = "zengrowth_operator_session"

# Loopback hosts that qualify for the dev bypass (shared with AuthGateMiddleware).
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver", "testclient"}


class LoginRequest(BaseModel):
    password: str


PROXY_TOKEN_HEADER = "x-zengrowth-proxy-token"


def _proxy_token_ok(request: Request, expected: str | None) -> bool:
    """True when the request carries the configured edge token.

    Compared as bytes: ``hmac.compare_digest`` raises ``TypeError`` on strings
    with non-ASCII characters, and this header is attacker-controlled, so a
    string comparison would turn a junk header into a 500 on the login route.
    """
    if not expected:
        return False
    presented = request.headers.get(PROXY_TOKEN_HEADER)
    if not presented:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def _peer_is_trusted_proxy(host: str | None, trusted: list[str]) -> bool:
    """True when the direct peer is an explicitly trusted reverse proxy.

    Deliberately *not* "any private address": on the shared Docker network the
    API sits beside other containers, so trusting the whole private range would
    let any sibling (or an SSRF into one) forge a different ``X-Real-IP`` on
    every login attempt and bypass the lockout — and nginx's edge limiter with
    it. Only peers matching ``LOGIN_TRUSTED_PROXIES`` may name the client.
    """
    if not host:
        return False
    if host in LOOPBACK_HOSTS:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    for entry in trusted:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _client_key(request: Request) -> str:
    """Throttle key: the real client, not the reverse proxy (SEC-04).

    The API is internal-only and reached through nginx, which connects over
    loopback or a Docker network. Keying on ``request.client.host`` therefore
    gave *every* caller the same key, so anyone could spend the operator's
    failed-attempt budget and lock them out. When the direct peer is internal we
    trust the proxy-set client address instead; a public peer (a direct hit on a
    published port) is keyed on itself and cannot spoof another client's key.

    Two ways to establish that the caller *is* the edge, in order:

    1. ``LOGIN_PROXY_TOKEN`` — a shared secret the edge adds as
       ``X-ZenGrowth-Proxy-Token``. Preferred whenever the API shares a Docker
       network, because peer addresses cannot tell nginx apart from a sibling
       container, and naming the whole subnet would trust every neighbour.
    2. ``LOGIN_TRUSTED_PROXIES`` — exact peer addresses or narrow CIDRs
       (loopback by default).

    The edge must also set ``X-Real-IP`` (both shipped nginx configs do). Behind
    an additional CDN, nginx needs ``set_real_ip_from``/``real_ip_header`` so
    ``$remote_addr`` is the end client — see RUNBOOK.md §8a.
    """
    settings = get_settings()
    peer = request.client.host if request.client else None
    if _proxy_token_ok(request, settings.login_proxy_token) or _peer_is_trusted_proxy(
        peer, settings.login_trusted_proxies
    ):
        for header in ("x-real-ip", "x-forwarded-for"):
            value = request.headers.get(header)
            if value:
                candidate = value.split(",")[0].strip()
                if candidate:
                    return candidate
    return peer or "unknown"


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    settings = get_settings()
    pw_hash = settings.zengrowth_operator_password_hash
    secret = settings.zengrowth_session_secret
    if not pw_hash or not secret:
        raise HTTPException(status_code=503, detail="operator auth is not configured")

    # App-level brute-force backoff behind the nginx edge limiter (SEC-04).
    throttle = getattr(request.app.state, "login_throttle", None)
    key = _client_key(request)
    if throttle is not None:
        wait = throttle.retry_after(key)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail="too many failed login attempts; try again later",
                headers={"Retry-After": str(wait)},
            )

    if not verify_password(payload.password, pw_hash):
        if throttle is not None:
            throttle.record_failure(key)
        raise HTTPException(status_code=401, detail="invalid credentials")

    if throttle is not None:
        throttle.reset(key)
    ttl = settings.zengrowth_session_ttl_seconds
    sid = secrets.token_urlsafe(32)
    create_operator_session(sid, ttl_seconds=ttl)
    cookie = make_session_cookie(secret, ttl_seconds=ttl, session_id=sid)
    response.set_cookie(
        SESSION_COOKIE,
        cookie,
        max_age=ttl,
        httponly=True,
        secure=settings.zengrowth_require_https,
        samesite="lax",
    )
    return {"status": "ok"}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    settings = get_settings()
    secret = settings.zengrowth_session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    if secret and cookie:
        payload = parse_session_cookie(secret, cookie)
        if payload:
            revoke_operator_session(str(payload["sid"]))
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "ok"}


@router.get("/auth/session")
def session(request: Request) -> dict:
    settings = get_settings()
    # Dev/loopback bypass mirrors AuthGateMiddleware so the SPA isn't walled at
    # /login during local development. It applies only when HTTPS is not required,
    # the request is from loopback, AND no operator is configured — i.e. there is
    # no password to log in with. Once an operator hash + secret are set (or in
    # production with require_https), the real cookie check applies.
    auth_configured = bool(
        settings.zengrowth_operator_password_hash and settings.zengrowth_session_secret
    )
    client_host = request.client.host if request.client else None
    if (
        not settings.zengrowth_require_https
        and not auth_configured
        and client_host in LOOPBACK_HOSTS
    ):
        return {"status": "ok"}

    secret = settings.zengrowth_session_secret
    cookie = request.cookies.get(SESSION_COOKIE)
    if not secret or not cookie or not is_live_session_cookie(secret, cookie):
        raise HTTPException(status_code=401, detail="not authenticated")
    return {"status": "ok"}
