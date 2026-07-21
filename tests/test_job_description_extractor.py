import json
from typing import Any

import pytest

from zengrowth.config import Settings
from zengrowth.ingestion.job_description_extractor import extract_job_fields
from zengrowth.llm_json import parse_json_strict


class FakeExtractor:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str]] = []

    def extract(self, system: str, user: str, model: str) -> dict[str, Any]:
        self.calls.append((system, user, model))
        return self.response


def test_parse_json_strict_accepts_plain_json():
    assert parse_json_strict('{"company": "Acme"}') == {"company": "Acme"}


def test_parse_json_strict_strips_code_fences():
    assert parse_json_strict('```json\n{"company": "Acme"}\n```') == {"company": "Acme"}


def test_parse_json_strict_raises_for_malformed_output():
    with pytest.raises(json.JSONDecodeError):
        parse_json_strict("not json")


def test_extract_job_fields_valid_complete_response():
    response = {
        "company": "Acme",
        "title": "Director of AI",
        "location": "London",
        "hybrid_policy": "2 days/week London",
        "compensation": {"min_gbp": 130000, "max_gbp": 160000},
        "seniority": "Director",
        "application_url": "https://example.com/job",
        "posting_date": "2026-05-20",
        "missing_fields": [],
        "confidence_notes": "All core fields were explicit.",
    }
    client = FakeExtractor(response)
    settings = Settings(anthropic_api_key="test", scoring_model="claude-test")

    extracted = extract_job_fields(
        raw_text="Lead AI strategy.",
        application_url="https://example.com/job",
        client=client,
        settings=settings,
    )

    assert extracted.company == "Acme"
    assert extracted.title == "Director of AI"
    assert extracted.compensation == {"min_gbp": 130000, "max_gbp": 160000}
    assert extracted.posting_date.isoformat() == "2026-05-20"
    assert extracted.description == "Lead AI strategy."
    assert len(client.calls) == 1
    assert client.calls[0][2] == "claude-test"


def test_extract_job_fields_fills_safe_defaults_for_missing_optional_fields():
    client = FakeExtractor(
        {
            "company": "Acme",
            "title": "AI Lead",
            "missing_fields": ["location", "posting_date"],
        }
    )
    settings = Settings(anthropic_api_key="test")

    extracted = extract_job_fields(
        raw_text="AI Lead role",
        application_url="https://example.com/job",
        client=client,
        settings=settings,
    )

    assert extracted.application_url == "https://example.com/job"
    assert extracted.description == "AI Lead role"
    assert extracted.location is None
    assert extracted.missing_fields == ["location", "posting_date"]


def test_extract_job_fields_rejects_non_object_compensation():
    client = FakeExtractor(
        {
            "company": "Acme",
            "title": "AI Lead",
            "compensation": "£150k",
            "description": "AI Lead role",
        }
    )
    settings = Settings(anthropic_api_key="test")

    with pytest.raises(ValueError, match="extraction response invalid"):
        extract_job_fields(raw_text="AI Lead role", client=client, settings=settings)
