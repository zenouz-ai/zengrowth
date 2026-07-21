"""Per-model pricing for LLM cost estimation (USD per 1M tokens).

Prices are approximate public list rates; override via ``llm_price_overrides`` in
settings. Follows OpenTelemetry gen_ai cost attribute naming in ``detail``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# USD per 1M tokens: input, output, cache_read, cache_write
_DEFAULT_PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_write": 3.75,
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


def cost_usd(
    model: str,
    usage: TokenUsage,
    *,
    price_overrides: dict[str, Any] | None = None,
) -> float:
    rates = _resolve_rates(model, price_overrides)
    billable_input = max(0, usage.input_tokens - usage.cache_read_tokens - usage.cache_creation_tokens)
    total = (
        billable_input * rates["input"]
        + usage.output_tokens * rates["output"]
        + usage.cache_read_tokens * rates["cache_read"]
        + usage.cache_creation_tokens * rates["cache_write"]
    ) / 1_000_000
    return round(total, 6)
