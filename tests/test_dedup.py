from datetime import date

from zengrowth.ingestion.dedup import dedup_hash, normalize


def test_normalize_lowercases_and_strips_punctuation():
    assert normalize("  Acme, Inc.  ") == "acme inc"


def test_dedup_hash_stable_for_same_inputs():
    a = dedup_hash("Acme Inc.", "Head of AI", date(2025, 5, 1))
    b = dedup_hash("acme  inc", "head of ai", date(2025, 5, 1))
    assert a == b


def test_dedup_hash_differs_on_company_or_date():
    base = dedup_hash("Acme", "Head of AI", date(2025, 5, 1))
    assert base != dedup_hash("Other", "Head of AI", date(2025, 5, 1))
    assert base != dedup_hash("Acme", "Head of AI", date(2025, 5, 2))
    assert base != dedup_hash("Acme", "Head of AI", None)


def test_dedup_hash_handles_none_date():
    a = dedup_hash("Acme", "Head of AI", None)
    b = dedup_hash("acme", "head of ai", None)
    assert a == b


def test_dedup_hash_external_id_ignores_volatile_fields():
    # Same stable posting id → same identity even when title/date wording drift
    # (the EA-01 fix: Greenhouse bumping updated_at must not re-ingest).
    a = dedup_hash("Acme", "Head of AI", date(2025, 5, 1), source="greenhouse", external_id="42")
    b = dedup_hash(
        "Acme", "Head of AI (Remote)", date(2025, 6, 9), source="greenhouse", external_id="42"
    )
    assert a == b


def test_dedup_hash_external_id_distinguishes_distinct_postings():
    # Distinct same-title reqs on the same day no longer false-collide.
    a = dedup_hash("Acme", "ML Engineer", date(2025, 5, 1), source="greenhouse", external_id="1")
    b = dedup_hash("Acme", "ML Engineer", date(2025, 5, 1), source="greenhouse", external_id="2")
    assert a != b


def test_dedup_hash_external_id_scoped_by_source():
    a = dedup_hash("Acme", "ML Engineer", None, source="greenhouse", external_id="1")
    b = dedup_hash("Acme", "ML Engineer", None, source="lever", external_id="1")
    assert a != b
