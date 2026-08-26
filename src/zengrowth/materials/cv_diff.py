"""Line-level diff between the base CV template and a tailored draft."""

from __future__ import annotations

import re
from typing import Any

_WS_RE = re.compile(r"\s+")


def normalize_cv_line(text: str) -> str:
    """Loose normalisation for same-meaning / minor LaTeX reword checks."""
    value = text or ""
    value = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r" \1 ", value)
    value = re.sub(r"\\[a-zA-Z]+", " ", value)
    value = value.replace("{", " ").replace("}", " ").replace("$", " ")
    value = _WS_RE.sub(" ", value).strip().lower()
    return value


def _tailored_experience(tailored: dict[str, Any]) -> list[list[str]]:
    raw = tailored.get("experience")
    if isinstance(raw, dict):
        rows: list[tuple[int, list[str]]] = []
        for key, bullets in raw.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            if isinstance(bullets, list):
                rows.append((index, [str(item) for item in bullets]))
        return [bullets for _, bullets in sorted(rows)]
    if isinstance(raw, list):
        return [[str(item) for item in role] for role in raw if isinstance(role, list)]
    return []


def summarize_cv_changes(original: dict[str, Any], tailored: dict[str, Any]) -> dict[str, Any]:
    """Compare parsed template content to the effective tailored draft."""
    changes: list[dict[str, Any]] = []
    lines_total = 0
    lines_changed = 0

    orig_summary = str(original.get("summary") or "")
    new_summary = str(tailored.get("summary") or "")
    if orig_summary or new_summary:
        lines_total += 1
        if normalize_cv_line(orig_summary) != normalize_cv_line(new_summary):
            lines_changed += 1
            changes.append(
                {
                    "section": "summary",
                    "index": 0,
                    "before": orig_summary,
                    "after": new_summary,
                }
            )

    orig_caps = [str(line) for line in (original.get("capabilities") or [])]
    new_caps = [str(line) for line in (tailored.get("capabilities") or [])]
    for index, (before, after) in enumerate(zip(orig_caps, new_caps, strict=False)):
        lines_total += 1
        if normalize_cv_line(before) != normalize_cv_line(after):
            lines_changed += 1
            changes.append(
                {
                    "section": "capability",
                    "index": index,
                    "before": before,
                    "after": after,
                }
            )

    orig_roles = original.get("experience") or []
    new_roles = _tailored_experience(tailored)
    for role_index, (before_role, after_role) in enumerate(
        zip(orig_roles, new_roles, strict=False)
    ):
        for bullet_index, (before, after) in enumerate(
            zip(before_role, after_role, strict=False)
        ):
            lines_total += 1
            if normalize_cv_line(str(before)) != normalize_cv_line(str(after)):
                lines_changed += 1
                changes.append(
                    {
                        "section": "experience",
                        "role_index": role_index,
                        "index": bullet_index,
                        "before": str(before),
                        "after": str(after),
                    }
                )

    lines_unchanged = max(lines_total - lines_changed, 0)
    change_rate = round(lines_changed / lines_total, 3) if lines_total else 0.0

    cap_changed = sum(1 for item in changes if item["section"] == "capability")
    bullet_changed = sum(1 for item in changes if item["section"] == "experience")

    return {
        "lines_total": lines_total,
        "lines_changed": lines_changed,
        "lines_unchanged": lines_unchanged,
        "change_rate": change_rate,
        "summary_changed": any(item["section"] == "summary" for item in changes),
        "capabilities_changed": cap_changed,
        "capabilities_total": len(orig_caps),
        "bullets_changed": bullet_changed,
        "bullets_total": sum(len(role) for role in orig_roles if isinstance(role, list)),
        "changes": changes,
    }
