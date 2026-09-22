"""Soft daily LLM-spend ceiling (SEC-08).

Every LLM call is already metered to ``LlmCall.cost_usd``; this turns that meter
into a guard. Once today's summed spend reaches ``llm_daily_budget_usd`` the next
billable call fails closed with ``BudgetExceededError`` (surfaced as 503 by the
API) instead of spending without limit. The cap is 0 by default, so nothing
changes until an operator opts in — a self-hoster's insurance against a
misconfiguration (a huge board list, a re-score loop) quietly running up a bill.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Session, select

from ..models import LlmCall


class BudgetExceededError(RuntimeError):
    """Raised when today's LLM spend has reached the configured daily ceiling."""

    def __init__(self, spent_usd: float, cap_usd: float) -> None:
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        super().__init__(
            f"Daily LLM budget reached: ${spent_usd:.2f} of ${cap_usd:.2f} spent today. "
            "New scoring/material/extraction calls are paused until 00:00 UTC. "
            "Raise LLM_DAILY_BUDGET_USD to continue."
        )


def today_spend_usd(session: Session, *, now: datetime | None = None) -> float:
    """Sum ``LlmCall.cost_usd`` since the start of the current UTC day."""
    now = now or datetime.now(UTC)
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    total = session.exec(
        select(func.coalesce(func.sum(LlmCall.cost_usd), 0.0)).where(LlmCall.timestamp >= start)
    ).one()
    # func.sum returns a scalar; SQLModel may wrap it in a 1-tuple depending on version.
    if isinstance(total, tuple):
        total = total[0]
    return float(total or 0.0)


def check_daily_budget(session: Session, cap_usd: float, *, now: datetime | None = None) -> None:
    """Raise ``BudgetExceededError`` when today's spend has reached ``cap_usd``.

    No-op when ``cap_usd`` <= 0 (disabled) or ``session`` is None (can't measure).
    """
    if cap_usd <= 0 or session is None:
        return
    spent = today_spend_usd(session, now=now)
    if spent >= cap_usd:
        raise BudgetExceededError(spent, cap_usd)
