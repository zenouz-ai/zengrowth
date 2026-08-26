"""Branding assets are committed, but the generator stays maintained."""

from pathlib import Path

from branding import generate_assets
from PIL import Image, ImageFont


def test_branding_font_resolution_finds_loadable_fonts():
    regular = generate_assets.resolve_font(
        "ZENGROWTH_BRAND_FONT_REGULAR",
        generate_assets.REGULAR_FONT_CANDIDATES,
    )
    bold = generate_assets.resolve_font(
        "ZENGROWTH_BRAND_FONT_BOLD",
        generate_assets.BOLD_FONT_CANDIDATES,
    )

    assert Path(regular).exists()
    assert Path(bold).exists()
    assert isinstance(ImageFont.truetype(regular, 12), ImageFont.FreeTypeFont)
    assert isinstance(ImageFont.truetype(bold, 12), ImageFont.FreeTypeFont)


def test_main_branding_assets_are_landscape_rgb():
    """The README's current main images are committed landscape RGB PNGs."""
    for name in ("logo.png", "poster.png"):
        path = generate_assets.HERE / name
        assert path.exists()
        with Image.open(path) as image:
            width, height = image.size
            assert width > height, f"{name} should be landscape"
            assert image.mode == "RGB"


def test_archived_programmatic_assets_have_expected_dimensions():
    expectations = {
        generate_assets.ARCHIVE / "banner.png": (1280, 320),
        generate_assets.ARCHIVE / "poster.png": (1200, 675),
    }

    for path, size in expectations.items():
        assert path.exists()
        with Image.open(path) as image:
            assert image.size == size
            assert image.mode == "RGB"
