"""Obsidian-style markdown envelope for internal interview materials."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from ..models import Job

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)
_H1_RE = re.compile(r"^#\s+[^\n]+\n+", re.MULTILINE)
_OLD_BANNER_RE = re.compile(
    r"^>\s*\*\*Internal (?:prep pack|debrief)[^\n]*\*\*[^\n]*\n+(?:>[^\n]*\n+)*",
    re.MULTILINE,
)
_TIP_CALLOUT_RE = re.compile(r"^>\s*\[!tip\][^\n]*(?:\n(?:>[^\n]*|\n))*", re.MULTILINE)
_WARNING_CALLOUT_RE = re.compile(r"^>\s*\[!warning\][^\n]*(?:\n>[^\n]*)*\n*", re.MULTILINE)
_LEADING_RULE_RE = re.compile(r"^---\s*\n+")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "artifact"


def _yaml_quote(value: str) -> str:
    if not value or any(ch in value for ch in '":\n[]{}#') or not value.isascii():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if any(not (ch.isalnum() or ch in " -_") for ch in value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


# Offer-stage documents are not interview prep; they get their own tag family
# and alias suffix so Obsidian vault searches stay truthful (OFF-01/OFF-03).
_OFFER_MATERIAL_TAGS = {
    "offer_evaluation": "offer-stage",
    "offer_response": "offer-stage",
    "onboarding_pack": "onboarding",
    "departure_pack": "departure",
}

_ALIAS_SUFFIXES = {
    "offer_evaluation": "Offer Evaluation",
    "offer_response": "Offer Response",
    "onboarding_pack": "Onboarding Pack",
    "departure_pack": "Departure Pack",
}


def _pack_tags(job: Job, material_type: str) -> list[str]:
    company_tag = slugify(job.company).replace("-", "-")
    family = _OFFER_MATERIAL_TAGS.get(material_type, "interview-prep")
    tags = [family, material_type.replace("_", "-"), "job-application"]
    if company_tag:
        tags.append(company_tag)
    return tags


def build_frontmatter(
    title: str,
    job: Job,
    *,
    material_type: str,
    updated: date | None = None,
) -> str:
    """YAML frontmatter matching operator Obsidian vault exports."""
    updated_str = (updated or datetime.now(UTC).date()).isoformat()
    suffix = _ALIAS_SUFFIXES.get(material_type, "Interview Pack")
    alias = f"{job.company} — {job.title} {suffix}"
    tags = _pack_tags(job, material_type)
    tag_line = ", ".join(tags)
    lines = [
        "---",
        f"title: {_yaml_quote(title)}",
        f"aliases: [{slugify(title)}, {_yaml_quote(alias)}]",
        "type: reference",
        "status: active",
        f"tags: [{tag_line}]",
        f"updated: {updated_str}",
        "related:",
        '  - "[[Interview Preparation]]"',
        "---",
        "",
    ]
    return "\n".join(lines)


def build_provenance_callout(*, web_search_used: bool, material_kind: str = "prep pack") -> str:
    if web_search_used:
        text = (
            "Internal prep pack — not an application document. Company and interviewer "
            "facts below come from unverified web research (sources at the end). Claims "
            "about your own experience cite your verified evidence bank inline."
        )
    else:
        text = (
            "Internal prep pack — not an application document. Web research was unavailable "
            "for this pack, so company facts come only from the stored job description and "
            "summary — verify anything important yourself. Claims about your own experience "
            "cite your verified evidence bank inline."
        )
    if material_kind == "debrief":
        text = (
            "Internal debrief — private to you. Observations are grounded in your "
            "transcript or notes; anything from web research cites its source at the end."
        )
    elif material_kind == "offer_evaluation":
        if web_search_used:
            text = (
                "Internal offer evaluation — not an application document. Market figures "
                "below come from unverified web research (sources at the end); verify "
                "anything you rely on in a negotiation."
            )
        else:
            text = (
                "Internal offer evaluation — not an application document. Web research was "
                "unavailable, so market figures come only from stored context — verify "
                "benchmarks yourself before negotiating."
            )
    elif material_kind == "onboarding_pack":
        if web_search_used:
            text = (
                "Internal onboarding pack — private to you. Company facts from web research "
                "are unverified (sources at the end); process intelligence comes from your "
                "own debriefs and notes."
            )
        else:
            text = (
                "Internal onboarding pack — private to you. Web research was unavailable, so "
                "company facts come only from stored context; process intelligence comes "
                "from your own debriefs and notes."
            )
    elif material_kind == "departure_pack":
        text = (
            "Internal departure pack — private to you; nothing is sent by ZenGrowth. "
            "Check every date and obligation against your actual employment contract"
            + (
                "; statutory norms below come from unverified web research (sources at the end)."
                if web_search_used
                else " — web research was unavailable, so no statutory norms were looked up."
            )
        )
    return f"> [!warning] {text}\n\n"


def build_sources_section(citations: list[dict[str, str]], *, limit: int = 25) -> str:
    if not citations:
        return ""
    lines = "\n".join(f"- [{c['title']}]({c['url']})" for c in citations[:limit])
    return f"\n\n## Sources\n\n{lines}\n"


def strip_llm_envelope(text: str) -> str:
    """Remove frontmatter, title, banners, and provenance callouts.

    Also strips the leading `---` rule and `> [!warning]` provenance callout the
    wrap helpers add, so re-reading a stored document (e.g. the learning loop or
    the counter-draft grounding path) yields content, not envelope.
    """
    body = text.strip()
    body = _FRONTMATTER_RE.sub("", body, count=1).strip()
    body = _OLD_BANNER_RE.sub("", body, count=1).strip()
    body = _H1_RE.sub("", body, count=1).strip()
    body = _LEADING_RULE_RE.sub("", body, count=1).strip()
    body = _WARNING_CALLOUT_RE.sub("", body, count=1).strip()
    return body


def extract_tip_callout(body: str) -> tuple[str | None, str]:
    """Pull the first Obsidian tip callout out of the body so it sits under the H1."""
    match = _TIP_CALLOUT_RE.search(body)
    if not match:
        return None, body
    tip = match.group(0).strip()
    remainder = (body[: match.start()] + body[match.end() :]).strip()
    return tip, remainder


def wrap_obsidian_pack(
    body: str,
    *,
    title: str,
    job: Job,
    pack_type: str,
    web_search_used: bool,
    citations: list[dict[str, str]],
) -> str:
    """Assemble a full Obsidian-style prep pack from LLM section body."""
    cleaned = strip_llm_envelope(body)
    tip, cleaned = extract_tip_callout(cleaned)
    parts = [
        build_frontmatter(title, job, material_type=pack_type),
        f"# {title}",
    ]
    if tip:
        parts.extend(["", tip])
    parts.extend(["", "---", "", build_provenance_callout(web_search_used=web_search_used), cleaned])
    document = "\n".join(parts).rstrip() + build_sources_section(citations)
    return document + "\n"


def wrap_offer_document(
    body: str,
    *,
    title: str,
    job: Job,
    material_type: str,
    web_search_used: bool,
    citations: list[dict[str, str]],
) -> str:
    """Obsidian envelope for offer-stage documents (OFF-01/OFF-03)."""
    cleaned = strip_llm_envelope(body)
    parts = [
        build_frontmatter(title, job, material_type=material_type),
        f"# {title}",
        "",
        "---",
        "",
        build_provenance_callout(web_search_used=web_search_used, material_kind=material_type),
        cleaned,
    ]
    return "\n".join(parts).rstrip() + build_sources_section(citations) + "\n"


def wrap_obsidian_debrief(
    body: str,
    *,
    title: str,
    job: Job,
    web_search_used: bool,
    citations: list[dict[str, str]],
) -> str:
    cleaned = strip_llm_envelope(body)
    parts = [
        build_frontmatter(title, job, material_type="debrief"),
        f"# {title}",
        "",
        "---",
        "",
        build_provenance_callout(web_search_used=web_search_used, material_kind="debrief"),
        cleaned,
    ]
    document = "\n".join(parts).rstrip() + build_sources_section(citations, limit=15)
    return document + "\n"
