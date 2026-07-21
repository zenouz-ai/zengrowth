"""Tests for material export filenames."""

from zengrowth.materials.names import file_token, material_export_basename, material_export_filename
from zengrowth.models import GeneratedMaterial


def test_file_token_sanitizes_company():
    assert file_token("Anthropic") == "Anthropic"
    assert file_token("Stripe, Inc.") == "Stripe_Inc"


def test_material_export_basename_cv():
    name = material_export_basename(
        candidate="Jordan_Avery",
        material_type="cv",
        company="Anthropic",
        version=1,
    )
    assert name == "Jordan_Avery_CV_Anthropic_v1"


def test_material_export_basename_cover_letter():
    name = material_export_basename(
        candidate="Jordan_Avery",
        material_type="cover_letter",
        company="Netflix",
        version=2,
    )
    assert name == "Jordan_Avery_CL_Netflix_v2"


def test_material_export_basename_offer_stage_types():
    """Offer-stage artifacts get stable short type codes in download names."""
    assert (
        material_export_basename(
            candidate="Jordan_Avery",
            material_type="offer_evaluation",
            company="Acme",
            version=1,
        )
        == "Jordan_Avery_OfferEval_Acme_v1"
    )
    assert (
        material_export_basename(
            candidate="Jordan_Avery",
            material_type="departure_pack",
            company="Acme",
            version=2,
        )
        == "Jordan_Avery_Depart_Acme_v2"
    )


def test_material_export_filename_pdf():
    material = GeneratedMaterial(
        job_id=1,
        material_type="cv",
        title="CV",
        evidence_ids=[],
        version=3,
        status="created_pdf",
    )
    assert (
        material_export_filename(
            material, company="Figma", candidate="Jordan_Avery", kind="pdf"
        )
        == "Jordan_Avery_CV_Figma_v3.pdf"
    )
