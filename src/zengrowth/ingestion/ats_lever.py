"""Lever postings API client.

Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json
Public, no auth. Returns a list of postings with descriptionPlain available.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx

from ..models import Job, JobSource
from .dedup import dedup_hash

LEVER_BASE = "https://api.lever.co/v0/postings"


def _epoch_ms_to_date(value: int | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=UTC).date()
    except (OSError, OverflowError, ValueError):
        return None


def parse_lever_job(slug: str, payload: dict) -> Job:
    title = (payload.get("text") or "").strip()
    categories = payload.get("categories") or {}
    location = categories.get("location") if isinstance(categories, dict) else None
    commitment = categories.get("commitment") if isinstance(categories, dict) else None
    workplace_type = (
        payload.get("workplaceType")
        or (categories.get("allLocations") if isinstance(categories, dict) else None)
    )
    posting_date = _epoch_ms_to_date(payload.get("createdAt") or payload.get("updatedAt"))
    application_url = payload.get("hostedUrl") or payload.get("applyUrl")
    description = (payload.get("descriptionPlain") or payload.get("description") or "").strip() or None
    company = (payload.get("company") or slug).strip()

    # Lever posting ``id`` is a stable UUID; prefer it as the dedup identity so
    # edited/re-emitted postings are not re-ingested (EA-01).
    external_id = payload.get("id")
    external_id = str(external_id) if external_id is not None else None

    return Job(
        company=company,
        title=title,
        location=str(location) if location else None,
        hybrid_policy=str(workplace_type) if workplace_type else None,
        compensation=None,
        seniority=str(commitment) if commitment else None,
        application_url=application_url,
        posting_date=posting_date,
        description=description,
        source=JobSource.lever,
        # Scope the id by board slug for parity with Greenhouse (EA-01).
        dedup_hash=dedup_hash(
            company, title, posting_date, source=f"lever:{slug}", external_id=external_id
        ),
    )


def fetch_lever(slug: str, *, client: httpx.Client | None = None) -> list[Job]:
    own_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        url = f"{LEVER_BASE}/{slug}"
        resp = client.get(url, params={"mode": "json"})
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        return [parse_lever_job(slug, j) for j in data]
    finally:
        if own_client:
            client.close()
