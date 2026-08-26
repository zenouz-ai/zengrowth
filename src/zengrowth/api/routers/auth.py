"""Operator auth endpoints: login (set signed cookie), logout, session check."""

from __future__ import annotations

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


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


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
