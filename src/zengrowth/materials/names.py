"""Export filenames for generated CVs and cover letters.

On disk and in download headers we use a stable, human-readable pattern, e.g.
``Jordan_Avery_CV_Northwind_v1.pdf`` and ``Jordan_Avery_CL_Acme_v2.tex``.
"""

from __future__ import annotations

import re

from ..models import GeneratedMaterial

_TYPE_CODE = {
    "cv": "CV",
    "cover_letter": "CL",
    "answer": "Ans",
    # Internal interview artifacts (INT-01/02/03).
    "company_briefing": "Briefing",
    "interviewer_pack": "Panel",
    "tech_prep_pack": "TechPrep",
    "final_round_pack": "FinalPrep",
    "debrief": "Debrief",
    "email_draft": "Email",
    "interviewer_sim_prompt": "SimPrompt",
    # Offer stage (OFF-01/OFF-03/OFF-05).
    "offer_evaluation": "OfferEval",
    "offer_response": "OfferReply",
    "onboarding_pack": "Onboard",
    "departure_pack": "Depart",
}


def file_token(value: str, *, max_len: int = 48) -> str:
    """Sanitize a label for filesystem use (underscores, alphanumerics only)."""
    token = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip()).strip("_")
    return token[:max_len] or "Unknown"


def material_export_basename(
    *,
    candidate: str,
    material_type: str,
    company: str,
    version: int,
) -> str:
    """Base name without extension, e.g. ``Jordan_Avery_CV_Northwind_v1``."""
    type_code = _TYPE_CODE.get(material_type, file_token(material_type, max_len=8))
    candidate_token = file_token(candidate.replace(" ", "_"), max_len=32)
    company_token = file_token(company)
    return f"{candidate_token}_{type_code}_{company_token}_v{version}"


def material_export_filename(
    material: GeneratedMaterial,
    *,
    company: str,
    candidate: str,
    kind: str,
) -> str:
    """Download/export filename with extension."""
    ext = {"pdf": "pdf", "tex": "tex", "md": "md"}[kind]
    basename = material_export_basename(
        candidate=candidate,
        material_type=material.material_type,
        company=company,
        version=material.version,
    )
    return f"{basename}.{ext}"
