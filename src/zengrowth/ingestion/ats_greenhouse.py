"""Greenhouse boards API client.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Public JSON, no auth required. Returns a list of postings with content as
HTML; we strip tags to plain text for the description.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from html import unescape

import httpx

from ..models import Job, JobSource
from .dedup import dedup_hash

GREENHOUSE_BASE = "https://boards-api.greenhouse.io/v1/boards"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Stripping a tag leaves a space before punctuation ("roadmap ."); tidy it so
# the description reads as prose in every prompt built from it.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")


def _html_to_text(html: str | None) -> str | None:
    """Plain text from Greenhouse ``content``.

    Greenhouse returns the posting body as *HTML-entity-encoded* HTML
    (``&lt;p&gt;...``), so entities must be decoded **before** tags are
    stripped — stripping first left literal ``<p>`` markup in the stored
    description (and in every prompt built from it). Decoding twice also
    handles plain HTML input and double-encoded entities.
    """
    if not html:
        return None
    text = _TAG_RE.sub(" ", unescape(html))
    text = _WS_RE.sub(" ", unescape(text))
    return _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text).strip() or None


def _parse_posting_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_greenhouse_job(slug: str, payload: dict) -> Job:
    """Map one Greenhouse posting JSON object to a Job (unsaved)."""
    company = (payload.get("company_name") or slug).strip()
    title = (payload.get("title") or "").strip()
    location_obj = payload.get("location") or {}
    location = location_obj.get("name") if isinstance(location_obj, dict) else None
    # ``first_published`` is the real posting date; ``updated_at`` is bumped by
    # any edit, which made months-old postings look fresh to the recency filter.
    posting_date = _parse_posting_date(payload.get("first_published") or payload.get("updated_at"))
    description = _html_to_text(payload.get("content"))
    application_url = payload.get("absolute_url")

    metadata = payload.get("metadata") or []
    hybrid_policy = None
    for m in metadata if isinstance(metadata, list) else []:
        name = (m.get("name") or "").lower()
        if "remote" in name or "hybrid" in name or "office" in name:
            value = m.get("value")
            if value:
                hybrid_policy = str(value)
                break

    # Greenhouse posting ``id`` is stable across edits; prefer it as the dedup
    # identity so re-emitted/edited postings are not re-ingested (EA-01).
    external_id = payload.get("id")
    external_id = str(external_id) if external_id is not None else None

    return Job(
        company=company,
        title=title,
        location=location,
        hybrid_policy=hybrid_policy,
        compensation=None,
        seniority=None,
        application_url=application_url,
        posting_date=posting_date,
        description=description,
        source=JobSource.greenhouse,
        # Scope the id by board slug: Greenhouse posting ids are unique per board,
        # not globally, so two companies can share a numeric id (EA-01).
        dedup_hash=dedup_hash(
            company, title, posting_date, source=f"greenhouse:{slug}", external_id=external_id
        ),
    )


def fetch_greenhouse(slug: str, *, client: httpx.Client | None = None) -> list[Job]:
    own_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        url = f"{GREENHOUSE_BASE}/{slug}/jobs"
        resp = client.get(url, params={"content": "true"})
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs") or []
        return [parse_greenhouse_job(slug, j) for j in jobs]
    finally:
        if own_client:
            client.close()
