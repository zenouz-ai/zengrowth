"""Evaluation harness for the RAG generation + retrieval path.

Design: ``docs/EVAL.md``. Graded assessment: ``docs/audits/AUDIT-2026-06-rag-eval.md``.

This package holds the *reusable, deterministic* metric functions (EVAL-02/04).
They take no LLM and are safe to run on every PR. The golden set and the
pytest gates that consume these live under ``tests/eval/``.
"""

from .metrics import (
    forbidden_fact_hits,
    hard_fact_faithful,
    hard_fact_violations,
    kendall_tau,
    pairwise_f1,
    precision_at_k,
    recall_at_k,
)

__all__ = [
    "forbidden_fact_hits",
    "hard_fact_faithful",
    "hard_fact_violations",
    "kendall_tau",
    "pairwise_f1",
    "precision_at_k",
    "recall_at_k",
]
