"""Small shared helpers for strict JSON LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _extract_json_object(text: str) -> Any | None:
    """Recover the first valid JSON object embedded in surrounding prose.

    Models occasionally wrap the required JSON in commentary. Scan every ``{``
    and attempt to decode a full JSON value from there (``raw_decode`` correctly
    handles nested braces and braces inside strings), returning the first that
    parses to a dict.
    """
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index != -1:
        try:
            obj, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict):
            return obj
        index = text.find("{", index + 1)
    return None


def parse_json_strict(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        stripped = _FENCE_RE.sub("", text).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            recovered = _extract_json_object(stripped)
            if recovered is not None:
                return recovered
            raise
