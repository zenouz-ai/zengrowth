"""SEC-08: daily LLM-spend ceiling. Off by default; fails closed when tripped."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session

from zengrowth.config import Settings
from zengrowth.models import LlmCall, LlmCallStatus, LlmOperation
from zengrowth.observability.budget import (
    BudgetExceededError,
    check_daily_budget,
    today_spend_usd,
)
from zengrowth.observability.client import InstrumentedLLM


def _add_call(session: Session, cost: float, *, when: datetime | None = None) -> None:
    session.add(
        LlmCall(
            timestamp=when or datetime.now(UTC),
            operation=LlmOperation.chat,
            provider="anthropic",
            request_model="claude-sonnet-4-6",
            operation_name="score_job",
            cost_usd=cost,
            status=LlmCallStatus.ok,
        )
    )
    session.commit()


def test_today_spend_sums_only_todays_calls(session: Session) -> None:
    _add_call(session, 0.10)
    _add_call(session, 0.25)
    _add_call(session, 9.99, when=datetime.now(UTC) - timedelta(days=2))
    assert today_spend_usd(session) == pytest.approx(0.35)


def test_check_budget_is_noop_when_disabled(session: Session) -> None:
    _add_call(session, 100.0)
    check_daily_budget(session, 0.0)  # cap 0 = disabled, must not raise


def test_check_budget_is_noop_without_session() -> None:
    check_daily_budget(None, 5.0)  # nothing to measure, must not raise


def test_check_budget_passes_below_cap(session: Session) -> None:
    _add_call(session, 1.0)
    check_daily_budget(session, 5.0)  # under cap, must not raise


def test_check_budget_raises_at_cap(session: Session) -> None:
    _add_call(session, 3.0)
    _add_call(session, 2.5)
    with pytest.raises(BudgetExceededError) as excinfo:
        check_daily_budget(session, 5.0)
    assert excinfo.value.cap_usd == 5.0
    assert excinfo.value.spent_usd == pytest.approx(5.5)


def test_chat_fails_closed_when_over_budget_without_calling_provider(session: Session) -> None:
    _add_call(session, 10.0)
    llm = InstrumentedLLM(Settings(_env_file=None, llm_daily_budget_usd=5.0))
    # Budget is checked before any provider client is built, so a missing API key
    # is never reached: the call fails closed with the budget error.
    with pytest.raises(BudgetExceededError):
        llm.chat(
            system="s",
            user="u",
            model="claude-sonnet-4-6",
            max_tokens=10,
            operation_name="score_job",
            session=session,
        )
