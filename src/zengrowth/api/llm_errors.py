"""Map LLM provider exceptions to HTTP responses with operator-readable detail."""

from __future__ import annotations

from fastapi import HTTPException


def llm_http_exception(exc: Exception) -> HTTPException:
    """Convert Anthropic/SDK failures into 502/503/504 with string ``detail``."""
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=502, detail=str(exc))

    name = type(exc).__name__
    message = str(exc).strip() or name

    if "Authentication" in name:
        return HTTPException(
            status_code=503,
            detail="Claude API key rejected — reconnect your key in Setup.",
        )
    if "PermissionDenied" in name:
        return HTTPException(
            status_code=503,
            detail="Claude API access denied — check your key and account permissions.",
        )
    if "RateLimit" in name:
        return HTTPException(
            status_code=503,
            detail="Claude rate limit hit — wait a moment and try again.",
        )
    if "APITimeout" in name or "Timeout" in name:
        return HTTPException(
            status_code=504,
            detail="Generation timed out — try again.",
        )
    if "APIConnection" in name or "ConnectError" in name:
        return HTTPException(
            status_code=503,
            detail="Could not reach Claude — check network connectivity and try again.",
        )
    return HTTPException(status_code=502, detail=f"Generation failed: {message}")
