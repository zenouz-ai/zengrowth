"""Discovery domain: Tavily search returning links only (no auto-fetch)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ...db import get_session
from ...ingestion.tavily_search import discover
from ...models import DiscoverySearch
from ..schemas import DiscoveryHit, DiscoveryQuery, DiscoverySearchOut

router = APIRouter(tags=["discovery"])


def _hits_to_json(hits: list[DiscoveryHit]) -> list[dict]:
    return [h.model_dump() for h in hits]


def _hits_from_json(rows: list[dict] | None) -> list[DiscoveryHit]:
    if not rows:
        return []
    return [DiscoveryHit.model_validate(row) for row in rows]


@router.post("/discovery/search", response_model=list[DiscoveryHit])
def discovery_search(payload: DiscoveryQuery, session: Session = Depends(get_session)) -> list[DiscoveryHit]:
    try:
        run = discover(payload.query, max_results=payload.max_results, session=session)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    hits = [
        DiscoveryHit(title=h.title, url=h.url, snippet=h.snippet, score=h.score) for h in run.results
    ]
    record = DiscoverySearch(
        query=run.query,
        scoped_query=run.scoped_query,
        result_count=len(hits),
        results=_hits_to_json(hits),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return hits


@router.get("/discovery/searches", response_model=list[DiscoverySearchOut])
def list_discovery_searches(
    limit: int = 20,
    session: Session = Depends(get_session),
) -> list[DiscoverySearchOut]:
    stmt = select(DiscoverySearch).order_by(DiscoverySearch.created_at.desc()).limit(limit)  # type: ignore[union-attr]
    rows = list(session.exec(stmt))
    return [
        DiscoverySearchOut(
            id=row.id or 0,
            query=row.query,
            scoped_query=row.scoped_query,
            result_count=row.result_count,
            results=_hits_from_json(row.results),
            created_at=row.created_at,
        )
        for row in rows
    ]
