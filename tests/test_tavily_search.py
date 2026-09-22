"""Tests for Tavily discovery query scoping and URL filtering."""

from zengrowth.ingestion.tavily_search import (
    DiscoveryResult,
    build_scoped_query,
    filter_job_postings,
    looks_like_job_posting,
)


def test_build_scoped_query_wraps_user_input():
    scoped = build_scoped_query("Head of AI London")
    assert "Head of AI London" in scoped
    assert "job opening" in scoped.lower()


def test_looks_like_job_posting_accepts_ats_urls():
    assert looks_like_job_posting("https://boards.greenhouse.io/acme/jobs/123")
    assert looks_like_job_posting("https://jobs.lever.co/acme/abc-def")
    assert looks_like_job_posting("https://www.linkedin.com/jobs/view/123")


def test_looks_like_job_posting_rejects_generic_pages():
    assert not looks_like_job_posting("https://example.com/blog/ai-trends")
    assert not looks_like_job_posting("")


def test_filter_job_postings_keeps_only_postings():
    results = [
        DiscoveryResult(title="Role", url="https://boards.greenhouse.io/co/jobs/1"),
        DiscoveryResult(title="Blog", url="https://example.com/news"),
    ]
    filtered = filter_job_postings(results)
    assert len(filtered) == 1
    assert "greenhouse" in filtered[0].url
