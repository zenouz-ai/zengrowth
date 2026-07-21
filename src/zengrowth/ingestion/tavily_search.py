"""Tavily-backed discovery search.

Returns link metadata only. We do NOT auto-fetch or scrape the linked pages —
the user reviews results and uses the dashboard's manual-entry form for
anything worth ingesting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlmodel import Session

from ..config import Settings, get_settings
from ..observability.tracing import tool_step


@dataclass
class DiscoveryResult:
    title: str
    url: str
    snippet: str | None = None
    score: float | None = None


@dataclass
class DiscoveryRun:
    query: str
    scoped_query: str
    results: list[DiscoveryResult]


# URL path/host hints that a link is a real job posting (not a blog or news page).
_JOB_URL_RE = re.compile(
    r"(?:"
    r"boards\.greenhouse\.io|"
    r"jobs\.lever\.co|"
    r"jobs\.ashbyhq\.com|"
    r"myworkdayjobs\.com|"
    r"smartrecruiters\.com|"
    r"icims\.com|"
    r"workable\.com|"
    r"teamtailor\.com|"
    r"linkedin\.com/jobs|"
    r"/careers?/|"
    r"/jobs?/|"
    r"/job/|"
    r"/positions?/|"
    r"/openings?/|"
    r"/apply(?:/|$)"
    r")",
    re.IGNORECASE,
)


def build_scoped_query(query: str) -> str:
    """Wrap the operator query with job-posting intent."""
    stripped = query.strip()
    if not stripped:
        return stripped
    return (
        f"{stripped} job opening apply now careers "
        f'"{stripped}" site:greenhouse.io OR site:lever.co OR site:linkedin.com/jobs'
    )


def looks_like_job_posting(url: str) -> bool:
    """Heuristic filter: keep URLs that look like applyable job postings."""
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host_path = f"{parsed.netloc}{parsed.path}"
    return bool(_JOB_URL_RE.search(host_path))


def filter_job_postings(results: list[DiscoveryResult]) -> list[DiscoveryResult]:
    return [item for item in results if looks_like_job_posting(item.url)]


def discover(
    query: str,
    *,
    max_results: int = 10,
    session: Session | None = None,
    settings: Settings | None = None,
) -> DiscoveryRun:
    settings = settings or get_settings()
    api_key = settings.require_tavily_key()
    scoped_query = build_scoped_query(query)
    include_domains = settings.tavily_job_domains or None

    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)

    def _search() -> DiscoveryRun:
        kwargs: dict = {
            "query": scoped_query,
            "max_results": max(max_results * 3, 15),
            "search_depth": "advanced",
        }
        if include_domains:
            kwargs["include_domains"] = include_domains
        raw = client.search(**kwargs)
        items = raw.get("results", []) if isinstance(raw, dict) else []
        mapped = [
            DiscoveryResult(
                title=str(item.get("title") or item.get("url") or ""),
                url=str(item.get("url") or ""),
                snippet=item.get("content"),
                score=item.get("score"),
            )
            for item in items
            if item.get("url")
        ]
        filtered = filter_job_postings(mapped)
        if not filtered and mapped:
            # If the job filter is too strict, fall back to top Tavily hits with URLs.
            filtered = mapped
        return DiscoveryRun(
            query=query.strip(),
            scoped_query=scoped_query,
            results=filtered[:max_results],
        )

    if session is not None:
        with tool_step(
            session,
            step_name="tavily_search",
            step_type="tool",
            detail={"query": query, "scoped_query": scoped_query, "max_results": max_results},
        ):
            return _search()
    return _search()
