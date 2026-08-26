"""Tests for LLM exception → HTTP mapping."""

from zengrowth.api.llm_errors import llm_http_exception


def test_runtime_error_maps_to_503():
    exc = llm_http_exception(RuntimeError("ANTHROPIC_API_KEY is required"))
    assert exc.status_code == 503
    assert "ANTHROPIC_API_KEY" in exc.detail


def test_authentication_error_name_maps_to_key_message():
    class AuthenticationError(Exception):
        pass

    exc = llm_http_exception(AuthenticationError("invalid x-api-key"))
    assert exc.status_code == 503
    assert "Claude API key rejected" in exc.detail


def test_value_error_maps_to_502():
    exc = llm_http_exception(ValueError("pack generation returned an empty document"))
    assert exc.status_code == 502
    assert "empty document" in exc.detail


def test_timeout_maps_to_504():
    class APITimeoutError(Exception):
        pass

    exc = llm_http_exception(APITimeoutError("timed out"))
    assert exc.status_code == 504
    assert "timed out" in exc.detail.lower()
