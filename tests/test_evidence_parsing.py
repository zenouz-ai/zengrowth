from zengrowth.materials.evidence import parse_evidence_markdown


def test_parse_evidence_markdown_reads_blocks():
    md = """
## evi-001
- category: leadership
- source_role: Head of DS
- verified: true
- tags: leadership, hiring
- claim: |
    Built and led a DS team from 3 to 14.

## evi-002
- category: technical
- verified: false
- claim: |
    Designed a forecasting platform.
""".strip()
    items = parse_evidence_markdown(md)
    assert {it.id for it in items} == {"evi-001", "evi-002"}
    by_id = {it.id: it for it in items}
    assert by_id["evi-001"].verified is True
    assert by_id["evi-001"].tags == ["leadership", "hiring"]
    assert "Built and led" in by_id["evi-001"].claim_text
    assert by_id["evi-002"].verified is False
