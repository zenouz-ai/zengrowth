"""Per-model pricing for LLM cost estimation (USD per 1M tokens).

Prices are approximate public list rates; override via ``llm_price_overrides`` in
settings. Follows OpenTelemetry gen_ai cost attribute naming in ``detail``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Anthropic bills the server-side web_search tool per search ($10 / 1k searches),
# separately from tokens. Prep packs, offer evaluations, and journey summaries all
# use it, so leaving it out understated their cost and let the daily ceiling
# (SEC-08) overspend. Override with ``llm_price_overrides["web_search"]``.
WEB_SEARCH_USD_PER_REQUEST = 0.01

# USD per 1M tokens: input, output, cache_read, cache_write
# Rates from Anthropic public list (2026-07); Sonnet 5 intro pricing $2/$10 through
# 2026-08-31 — we book the standard $3/$15 so cost ceilings stay conservative.
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-opus-5": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_write": 6.25,
    },
    "claude-fable-5": {
        "input": 10.0,
        "output": 50.0,
        "cache_read": 1.0,
        "cache_write": 12.5,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-opus-4-8": {
        "input": 5.0,
        "output": 25.0,
        "cache_read": 0.50,
        "cache_write": 6.25,
    },
    "claude-sonnet-4-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-3-5-sonnet-20241022": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "text-embedding-3-small": {
        "input": 0.02,
        "output": 0.0,
        "cache_read": 0.0,
        "cache_write": 0.0,
    },
    "text-embedding-3-large": {
        "input": 0.13,
        "output": 0.0,
        "cache_read": 0.0,
        "cache_write": 0.0,
    },
}


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_anthropic(cls, usage: Any) -> TokenUsage:
        if usage is None:
            return cls()
        return cls(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            cache_creation_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        )

    @classmethod
    def from_openai_embedding(cls, usage: Any, *, text_count: int) -> TokenUsage:
        if usage is None:
            # Embeddings API returns total_tokens; attribute all to input.
            return cls(input_tokens=text_count * 4)
        return cls(input_tokens=int(getattr(usage, "total_tokens", 0) or 0))


def _resolve_rates(model: str, overrides: dict[str, Any] | None) -> dict[str, float]:
    if overrides and model in overrides:
        raw = overrides[model]
        if isinstance(raw, dict):
            return {
                "input": float(raw.get("input", 0)),
                "output": float(raw.get("output", 0)),
                "cache_read": float(raw.get("cache_read", 0)),
                "cache_write": float(raw.get("cache_write", 0)),
            }
    if model in _DEFAULT_PRICES:
        return _DEFAULT_PRICES[model]
    # Prefix match for versioned model ids (e.g. claude-sonnet-4-6-20260301)
    for key, rates in _DEFAULT_PRICES.items():
        if model.startswith(key):
            return rates
    # Conservative fallback for unknown chat models
    return {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75}


def _web_search_rate(price_overrides: dict[str, Any] | None) -> float:
    raw = (price_overrides or {}).get("web_search")
    if isinstance(raw, dict) and "per_request" in raw:
        return float(raw["per_request"])
    if isinstance(raw, int | float):
        return float(raw)
    return WEB_SEARCH_USD_PER_REQUEST


def cost_usd(
    model: str,
    usage: TokenUsage,
    *,
    price_overrides: dict[str, Any] | None = None,
    web_search_requests: int = 0,
) -> float:
    """Estimated USD cost of one call.

    Anthropic reports ``input_tokens`` *exclusive* of cached tokens
    (``cache_read_input_tokens`` / ``cache_creation_input_tokens`` are additive,
    separately priced counts), so the uncached input is ``input_tokens`` as-is —
    subtracting the cache counts from it would undercharge any cached call.
    """
    rates = _resolve_rates(model, price_overrides)
    total = (
        usage.input_tokens * rates["input"]
        + usage.output_tokens * rates["output"]
        + usage.cache_read_tokens * rates["cache_read"]
        + usage.cache_creation_tokens * rates["cache_write"]
    ) / 1_000_000
    total += max(0, web_search_requests) * _web_search_rate(price_overrides)
    return round(total, 6)
