"""Golden-set loader + builders for the eval harness (EVAL-01).

Reads the JSON cases under ``tests/eval/golden/`` and builds the same ``Job`` /
``ParsedEvidence`` objects the production code operates on, so the metrics run
against real types rather than dicts.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from zengrowth.ingestion.dedup import dedup_hash
from zengrowth.materials.evidence import ParsedEvidence
from zengrowth.models import Job, JobSource

GOLDEN_DIR = Path(__file__).parent / "golden"


def load_golden(name: str) -> dict[str, Any]:
    """Full golden document, for sets with sections beyond a flat case list."""
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def load_cases(name: str) -> list[dict[str, Any]]:
    return load_golden(name)["cases"]


def build_job(spec: dict[str, Any]) -> Job:
    posting = date(2026, 5, 20)
    return Job(
        company=spec.get("company", "Acme"),
        title=spec.get("title", "Engineer"),
        location=spec.get("location"),
        posting_date=posting,
        description=spec.get("description", ""),
        source=JobSource.manual,
        dedup_hash=dedup_hash(spec.get("company", "Acme"), spec.get("title", "Engineer"), posting),
        job_summary=spec.get("job_summary"),
        fit_score=spec.get("fit_score"),
    )


def build_evidence(bank: list[dict[str, Any]]) -> list[ParsedEvidence]:
    return [
        ParsedEvidence(
            id=item["id"],
            category=item.get("category", "general"),
            claim_text=item["claim_text"],
            source_role=item.get("source_span"),
            verified=True,
            tags=item.get("tags", []),
        )
        for item in bank
    ]
