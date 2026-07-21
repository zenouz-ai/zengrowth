"""Operator settings: in-app API-key setup + first-run status (PS-P1).

Lets a first-time operator add an LLM API key and check setup progress from the
dashboard instead of editing ``.env``. The key is validated with a cheap ping,
stored encrypted (``secrets_store``), and injected into the running ``Settings``
singleton so every later LLM client uses it with no restart. Gated by the auth
middleware like every other ``/api`` route.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from ...config import get_settings
from ...db import get_session
from ...knowledge.service import active_cv_template_text
from ...models import ClaimVerificationState, EvidenceClaim, SourceDocument
from ...secrets_store import (
    SECRET_PROVIDERS,
    delete_secret,
    list_secret_names,
    set_secret,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsStatus(BaseModel):
    anthropic_configured: bool
    anthropic_source: str | None  # "env" | "stored" | None
    tavily_configured: bool
    openai_configured: bool
    has_documents: bool
    has_verified_facts: bool
    has_cv_template: bool
    setup_complete: bool


class KeyUpdate(BaseModel):
    provider: str = Field(description="anthropic | tavily | openai")
    key: str = Field(min_length=8)


def _validate_anthropic_key(key: str, model: str) -> None:
    """Cheap auth check: a 1-token completion. Raises ValueError if rejected.

    Isolated so the test suite can monkeypatch it instead of hitting the network.
    """
    from anthropic import Anthropic

    try:
        client = Anthropic(api_key=key)
        client.messages.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "ping"}],
        )
    except Exception as exc:  # noqa: BLE001 - surface any auth/transport failure as invalid
        name = type(exc).__name__
        if "Authentication" in name or "Permission" in name:
            raise ValueError("The API key was rejected by Anthropic.") from exc
        raise ValueError(f"Could not validate the key ({name}).") from exc


def build_status(session: Session) -> SettingsStatus:
    settings = get_settings()
    stored = list_secret_names(session)

    def source(provider: str, attr: str) -> str | None:
        if not getattr(settings, attr):
            return None
        return "stored" if provider in stored else "env"

    anthropic_attr = SECRET_PROVIDERS["anthropic"]
    has_documents = session.exec(
        select(SourceDocument.id).where(SourceDocument.is_current == True)  # noqa: E712
    ).first() is not None
    has_verified_facts = session.exec(
        select(EvidenceClaim.id).where(
            EvidenceClaim.verification_state == ClaimVerificationState.verified
        )
    ).first() is not None
    has_cv_template = active_cv_template_text(session) is not None

    anthropic_configured = bool(getattr(settings, anthropic_attr))
    return SettingsStatus(
        anthropic_configured=anthropic_configured,
        anthropic_source=source("anthropic", anthropic_attr),
        tavily_configured=bool(settings.tavily_api_key),
        openai_configured=bool(settings.openai_api_key),
        has_documents=has_documents,
        has_verified_facts=has_verified_facts,
        has_cv_template=has_cv_template,
        # Setup is "done enough" once the key exists and the engine has facts to draw on.
        setup_complete=anthropic_configured and has_verified_facts,
    )


@router.get("/status", response_model=SettingsStatus)
def get_status(session: Session = Depends(get_session)) -> SettingsStatus:
    return build_status(session)


@router.put("/keys", response_model=SettingsStatus)
def put_key(payload: KeyUpdate, session: Session = Depends(get_session)) -> SettingsStatus:
    provider = payload.provider.strip().lower()
    if provider not in SECRET_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'.")
    key = payload.key.strip()
    settings = get_settings()
    if provider == "anthropic":
        try:
            _validate_anthropic_key(key, settings.scoring_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_secret(session, provider, key, settings=settings)
    # Inject into the running process: the cached Settings singleton is read lazily
    # by every InstrumentedLLM, so no restart is needed.
    setattr(settings, SECRET_PROVIDERS[provider], key)
    return build_status(session)


@router.delete("/keys/{provider}", response_model=SettingsStatus)
def delete_key(provider: str, session: Session = Depends(get_session)) -> SettingsStatus:
    provider = provider.strip().lower()
    if provider not in SECRET_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'.")
    delete_secret(session, provider)
    # Drop the in-process value too. Env-sourced keys are reloaded on next boot.
    settings = get_settings()
    import os

    env_var = SECRET_PROVIDERS[provider].upper()
    if not os.environ.get(env_var):
        setattr(settings, SECRET_PROVIDERS[provider], None)
    return build_status(session)
