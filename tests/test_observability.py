"""Tests for observability pricing, tracing, and API."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from zengrowth.models import LlmCall, LlmCallStatus, LlmOperation, PipelineRun, PipelineRunStatus
from zengrowth.observability.client import InstrumentedLLM
from zengrowth.observability.pricing import TokenUsage, cost_usd
from zengrowth.observability.tracing import pipeline_run, start_trace, tool_step


def test_cost_usd_anthropic_sonnet():
    usage = TokenUsage(input_tokens=1000, output_tokens=500)
    cost = cost_usd("claude-sonnet-4-6", usage)
    assert cost == pytest.approx(0.0105, rel=1e-3)


def test_start_trace_sets_context():
    trace = start_trace()
    assert len(trace) == 32


def test_pipeline_run_creates_row(session: Session):
    with pipeline_run(session, pipeline_type="test_pipeline"):
        pass
    runs = list(session.exec(select(PipelineRun)))
    assert len(runs) == 1
    assert runs[0].status == PipelineRunStatus.completed
    assert runs[0].pipeline_type == "test_pipeline"


def test_tool_step_records_pipeline_step(session: Session):
    with pipeline_run(session, pipeline_type="test"), tool_step(
        session, step_name="fetch_board", step_type="tool"
    ):
        pass
    run = session.exec(select(PipelineRun)).first()
    assert run is not None
    assert run.step_count >= 1


class FakeInstrumentedLLM:
    def chat_json(self, **kwargs):
        return {"summary": "ok", "_usage": {"input_tokens": 10, "output_tokens": 5}}

    def complete_text(self, **kwargs):
        return "text"

    def embed(self, texts, **kwargs):
        return [[0.1, 0.2] for _ in texts]


def test_instrumented_llm_records_call(session, monkeypatch):
    from zengrowth.config import Settings

    settings = Settings(anthropic_api_key="test", feature_observability=True)

    class FakeMsg:
        content = [type("B", (), {"type": "text", "text": '{"a":1}'})()]
        usage = type("U", (), {"input_tokens": 100, "output_tokens": 20})()
        model = "claude-sonnet-4-6"
        stop_reason = "end_turn"

    class FakeAnthropic:
        def __init__(self, api_key: str):
            self.messages = self

        def create(self, **kwargs):
            return FakeMsg()

    monkeypatch.setattr(
        "zengrowth.observability.client.InstrumentedLLM._anthropic_client",
        lambda self: FakeAnthropic("x"),
    )
    llm = InstrumentedLLM(settings)
    result = llm.chat_json(
        system="s",
        user="u",
        model="claude-sonnet-4-6",
        max_tokens=100,
        operation_name="test_op",
        session=session,
    )
    assert result["a"] == 1
    rows = list(session.exec(select(LlmCall)))
    assert len(rows) == 1
    assert rows[0].operation_name == "test_op"
    assert rows[0].input_tokens == 100
    assert rows[0].status == LlmCallStatus.ok


def test_chat_forwards_temperature_only_when_set(session, monkeypatch):
    """TP-07: temperature is passed to the SDK only when a caller sets it."""
    from zengrowth.config import Settings

    settings = Settings(anthropic_api_key="test", feature_observability=True)
    captured: dict = {}

    class FakeMsg:
        content = [type("B", (), {"type": "text", "text": '{"a":1}'})()]
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
        model = "m"
        stop_reason = "end_turn"

    class FakeAnthropic:
        def __init__(self, api_key=None):
            self.messages = self

        def create(self, **kwargs):
            captured.clear()
            captured.update(kwargs)
            return FakeMsg()

    monkeypatch.setattr(
        "zengrowth.observability.client.InstrumentedLLM._anthropic_client",
        lambda self: FakeAnthropic(),
    )
    llm = InstrumentedLLM(settings)

    llm.chat_json(system="s", user="u", model="m", max_tokens=10, operation_name="op", session=session)
    assert "temperature" not in captured

    llm.chat_json(
        system="s", user="u", model="m", max_tokens=10, operation_name="op", session=session, temperature=0.0
    )
    assert captured["temperature"] == 0.0


def _fake_anthropic_sequence(responses: list[tuple[str, str]]):
    """Build a fake Anthropic client yielding (text, stop_reason) in order."""
    calls = {"n": 0}

    class FakeAnthropic:
        def __init__(self, api_key: str):
            self.messages = self

        def create(self, **kwargs):
            text, stop = responses[min(calls["n"], len(responses) - 1)]
            calls["n"] += 1

            class Msg:
                content = [type("B", (), {"type": "text", "text": text})()]
                usage = type("U", (), {"input_tokens": 10, "output_tokens": 5})()
                model = "claude-sonnet-4-6"
                stop_reason = stop

            return Msg()

    return FakeAnthropic, calls


def test_chat_json_repairs_malformed_then_succeeds(session, monkeypatch):
    from zengrowth.config import Settings

    settings = Settings(anthropic_api_key="test", feature_observability=True)
    FakeAnthropic, calls = _fake_anthropic_sequence(
        [("not json at all", "end_turn"), ('{"a": 1}', "end_turn")]
    )
    monkeypatch.setattr(
        "zengrowth.observability.client.InstrumentedLLM._anthropic_client",
        lambda self: FakeAnthropic("x"),
    )
    llm = InstrumentedLLM(settings)
    result = llm.chat_json(
        system="s", user="u", model="claude-sonnet-4-6", max_tokens=100,
        operation_name="test_repair", session=session,
    )
    assert result["a"] == 1
    assert calls["n"] == 2  # one repair re-ask
    # Both attempts recorded as separate auditable LlmCall rows.
    assert len(list(session.exec(select(LlmCall)))) == 2


def test_chat_json_treats_truncation_as_failure(session, monkeypatch):
    from zengrowth.config import Settings

    settings = Settings(anthropic_api_key="test", feature_observability=True)
    # First response parses but is flagged truncated; repair returns clean JSON.
    FakeAnthropic, calls = _fake_anthropic_sequence(
        [('{"a": 1}', "max_tokens"), ('{"a": 2}', "end_turn")]
    )
    monkeypatch.setattr(
        "zengrowth.observability.client.InstrumentedLLM._anthropic_client",
        lambda self: FakeAnthropic("x"),
    )
    llm = InstrumentedLLM(settings)
    result = llm.chat_json(
        system="s", user="u", model="claude-sonnet-4-6", max_tokens=100,
        operation_name="test_trunc", session=session,
    )
    assert result["a"] == 2
    assert calls["n"] == 2


def test_chat_json_raises_after_exhausting_repairs(session, monkeypatch):
    import json as _json

    from zengrowth.config import Settings

    settings = Settings(anthropic_api_key="test", feature_observability=True)
    FakeAnthropic, _ = _fake_anthropic_sequence([("still not json", "end_turn")])
    monkeypatch.setattr(
        "zengrowth.observability.client.InstrumentedLLM._anthropic_client",
        lambda self: FakeAnthropic("x"),
    )
    llm = InstrumentedLLM(settings)
    with pytest.raises(_json.JSONDecodeError):
        llm.chat_json(
            system="s", user="u", model="claude-sonnet-4-6", max_tokens=100,
            operation_name="test_fail", session=session, repair_attempts=1,
        )


def test_chat_json_validate_triggers_repair(session, monkeypatch):
    from zengrowth.config import Settings

    settings = Settings(anthropic_api_key="test", feature_observability=True)
    FakeAnthropic, calls = _fake_anthropic_sequence(
        [('{"a": 1}', "end_turn"), ('{"required": 1}', "end_turn")]
    )
    monkeypatch.setattr(
        "zengrowth.observability.client.InstrumentedLLM._anthropic_client",
        lambda self: FakeAnthropic("x"),
    )

    def validate(parsed):
        if "required" not in parsed:
            raise ValueError("missing required key")

    llm = InstrumentedLLM(settings)
    result = llm.chat_json(
        system="s", user="u", model="claude-sonnet-4-6", max_tokens=100,
        operation_name="test_validate", session=session, validate=validate,
    )
    assert result["required"] == 1
    assert calls["n"] == 2


def test_observability_summary_endpoint(session: Session):
    from collections.abc import Iterator

    from zengrowth.api.main import app
    from zengrowth.db import get_session

    def override_get_session() -> Iterator[Session]:
        yield session

    row = LlmCall(
        timestamp=datetime.now(UTC),
        operation=LlmOperation.chat,
        provider="anthropic",
        request_model="claude-sonnet-4-6",
        operation_name="score_job",
        input_tokens=50,
        output_tokens=10,
        latency_ms=120,
        cost_usd=0.001,
        status=LlmCallStatus.ok,
    )
    session.add(row)
    session.commit()

    app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(app)
        resp = client.get("/api/observability/summary")
        assert resp.status_code == 200
        body = resp.json()
        assert "today" in body
        assert body["today"]["call_count"] >= 1
    finally:
        app.dependency_overrides.clear()


def _obs_client(session: Session) -> TestClient:
    from collections.abc import Iterator

    from zengrowth.api.main import app
    from zengrowth.db import get_session

    def override_get_session() -> Iterator[Session]:
        yield session

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def test_observability_endpoints(session: Session):
    from zengrowth.api.main import app
    from zengrowth.models import (
        DataSource,
        DataSourceKind,
        PipelineRun,
        PipelineRunStatus,
        PipelineStep,
    )

    now = datetime.now(UTC)
    session.add(
        LlmCall(
            timestamp=now,
            operation=LlmOperation.chat,
            provider="anthropic",
            request_model="claude-sonnet-4-6",
            operation_name="summarize_job",
            input_tokens=30,
            output_tokens=10,
            latency_ms=80,
            cost_usd=0.0002,
            status=LlmCallStatus.ok,
        )
    )
    run = PipelineRun(
        trace_id="abc123",
        pipeline_type="ingestion",
        started_at=now,
        finished_at=now,
        status=PipelineRunStatus.completed,
        step_count=1,
    )
    session.add(run)
    session.add(
        PipelineStep(
            trace_id="abc123",
            span_id="span1",
            step_name="fetch_greenhouse",
            step_type="tool",
            started_at=now,
            duration_ms=42,
        )
    )
    session.add(DataSource(name="anthropic", kind=DataSourceKind.llm, enabled=True))
    session.commit()

    client = _obs_client(session)
    try:
        assert client.get("/api/observability/costs").status_code == 200
        assert client.get("/api/observability/latency").status_code == 200
        runs = client.get("/api/observability/runs")
        assert runs.status_code == 200
        assert runs.json()[0]["pipeline_type"] == "ingestion"
        detail = client.get("/api/observability/runs/abc123")
        assert detail.status_code == 200
        assert len(detail.json()["steps"]) == 1
        sources = client.get("/api/observability/datasources")
        assert sources.status_code == 200
        assert any(s["name"] == "anthropic" for s in sources.json())
        assert client.get("/api/observability/storage").status_code == 200
        perf = client.get("/api/observability/performance")
        assert perf.status_code == 200
        assert perf.json()[0]["operation_name"] == "summarize_job"
    finally:
        app.dependency_overrides.clear()


def test_observability_disabled_returns_503(session: Session, monkeypatch):
    from zengrowth.api.main import app
    from zengrowth.config import Settings

    monkeypatch.setattr(
        "zengrowth.api.routers.observability.get_settings",
        lambda: Settings(feature_observability=False),
    )
    client = _obs_client(session)
    try:
        assert client.get("/api/observability/summary").status_code == 503
    finally:
        app.dependency_overrides.clear()
