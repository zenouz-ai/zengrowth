"""Job dedup identity.

Two strategies, picked by whether the source exposes a stable posting id:

* **ATS feeds (Greenhouse/Lever)** key on ``source|external_id`` — the provider's
  immutable posting id. ATS feeds re-emit the same posting nightly and mutate
  volatile fields (Greenhouse bumps ``updated_at``), so a date-based key would
  re-insert and re-score the same role every run (EA-01). The stable id also
  stops two distinct same-title reqs posted on the same day from false-colliding.
* **Manual / paste / anything without a posting id** falls back to
  ``sha256(normalize(company) | normalize(title) | posting_date)``. These are
  operator-entered once, so the volatility problem does not apply.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = text.lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def dedup_hash(
    company: str,
    title: str,
    posting_date: date | None,
    *,
    source: str | None = None,
    external_id: str | None = None,
) -> str:
    """Stable identity for a job.

    When ``external_id`` is supplied (ATS postings), identity is the provider's
    immutable id scoped by ``source`` — independent of mutable fields like
    ``updated_at``/title wording. Otherwise it falls back to the normalized
    company|title|posting_date triple.
    """
    if external_id:
        payload = f"{normalize(source or '')}|{external_id.strip()}"
    else:
        posting = posting_date.isoformat() if posting_date else ""
        payload = f"{normalize(company)}|{normalize(title)}|{posting}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
