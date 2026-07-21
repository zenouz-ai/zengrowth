"""Render the legacy ZenGrowth programmatic marketing assets (banner + poster).

Run from the repo root:  python branding/generate_assets.py

Produces branding/archive/banner.png (1280x320) and
branding/archive/poster.png (1200x675) in the ZenGrowth palette: slate/indigo
base with a teal->violet accent.

These are retired assets kept for reference only. The README's current main
images are the landscape renders branding/logo.png and branding/poster.png,
which are NOT produced by this script — outputs go to archive/ so they never
overwrite the current mains.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE / "archive"

# --- Palette -----------------------------------------------------------------
BG_TOP = (15, 20, 38)        # deep slate
BG_BOT = (30, 27, 60)        # indigo
TEAL = (45, 212, 191)
VIOLET = (139, 122, 255)
INK = (233, 236, 248)
MUTED = (150, 158, 190)
GRID = (255, 255, 255)

REGULAR_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Microsoft/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
BOLD_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Microsoft/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _font_candidates(env_name: str, fallback_paths: tuple[str, ...]) -> tuple[str, ...]:
    override = os.environ.get(env_name)
    return (override, *fallback_paths) if override else fallback_paths


def resolve_font(env_name: str, fallback_paths: tuple[str, ...]) -> str:
    """Find a loadable TrueType/OpenType font path for deterministic PNG rendering."""
    attempted = _font_candidates(env_name, fallback_paths)
    for candidate in attempted:
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            ImageFont.truetype(str(path), 12)
        except OSError:
            continue
        return str(path)
    raise RuntimeError(
        f"No usable font found for {env_name}. Tried: {', '.join(attempted)}. "
        f"Set {env_name} to a valid TrueType/OpenType font path."
    )


FONT_REG = resolve_font("ZENGROWTH_BRAND_FONT_REGULAR", REGULAR_FONT_CANDIDATES)
FONT_BOLD = resolve_font("ZENGROWTH_BRAND_FONT_BOLD", BOLD_FONT_CANDIDATES)


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    w, h = size
    base = Image.new("RGB", size, top)
    grad = Image.new("L", (1, h))
    for y in range(h):
        grad.putpixel((0, y), int(255 * y / max(h - 1, 1)))
    grad = grad.resize(size)
    return Image.composite(Image.new("RGB", size, bottom), base, grad)


def dot_grid(img: Image.Image, step: int = 26, radius: int = 1, alpha: int = 16) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(step, img.height, step):
        for x in range(step, img.width, step):
            d.ellipse([x - radius, y - radius, x + radius, y + radius], fill=GRID + (alpha,))
    img.alpha_composite(overlay)


def grad_line(draw: ImageDraw.ImageDraw, p0, p1, c0, c1, width: int, steps: int = 60) -> None:
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        x0 = p0[0] + (p1[0] - p0[0]) * t0
        y0 = p0[1] + (p1[1] - p0[1]) * t0
        x1 = p0[0] + (p1[0] - p0[0]) * t1
        y1 = p0[1] + (p1[1] - p0[1]) * t1
        draw.line([x0, y0, x1, y1], fill=lerp(c0, c1, t0), width=width)


def glow_dot(draw: ImageDraw.ImageDraw, center, color, r=7) -> None:
    cx, cy = center
    for rr, a in ((r + 8, 40), (r + 4, 90), (r, 255)):
        draw.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=color + (a,))


def enso(draw: ImageDraw.ImageDraw, box, color, width=9) -> None:
    # Zen circle with a small opening (not fully closed).
    draw.arc(box, start=160, end=110, fill=color, width=width)


# --- Banner ------------------------------------------------------------------
def render_banner() -> Path:
    W, H = 1280, 320
    img = vertical_gradient((W, H), BG_TOP, BG_BOT).convert("RGBA")
    dot_grid(img)
    draw = ImageDraw.Draw(img)

    # Ensō mark
    enso(draw, [56, H // 2 - 52, 160, H // 2 + 52], TEAL, width=10)
    glow_dot(draw, (152, H // 2 - 36), VIOLET, r=6)

    # Wordmark + tagline
    draw.text((200, H // 2 - 64), "ZenGrowth", font=font(FONT_BOLD, 78), fill=INK)
    draw.text((204, H // 2 + 28), "A transparent career operating system",
              font=font(FONT_REG, 26), fill=MUTED)

    # Pipeline motif on the right: discover -> score -> generate -> track
    labels = ["Discover", "Score", "Generate", "Track"]
    xs = [820, 940, 1060, 1180]
    y = H // 2 + 12
    for i in range(len(xs) - 1):
        grad_line(draw, (xs[i], y), (xs[i + 1], y), TEAL, VIOLET, width=4)
    for i, x in enumerate(xs):
        glow_dot(draw, (x, y), lerp(TEAL, VIOLET, i / (len(xs) - 1)), r=8)
        lf = font(FONT_REG, 19)
        tw = draw.textlength(labels[i], font=lf)
        draw.text((x - tw / 2, y - 44), labels[i], font=lf, fill=INK)

    ARCHIVE.mkdir(exist_ok=True)
    out = ARCHIVE / "banner.png"
    img.convert("RGB").save(out, "PNG")
    return out


# --- Poster ------------------------------------------------------------------
def render_poster() -> Path:
    W, H = 1200, 675
    img = vertical_gradient((W, H), BG_TOP, BG_BOT).convert("RGBA")
    dot_grid(img, step=30)
    draw = ImageDraw.Draw(img)

    # Soft accent glow corners
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-160, -200, 260, 220], fill=TEAL + (26,))
    gd.ellipse([W - 260, H - 220, W + 160, H + 200], fill=VIOLET + (30,))
    img.alpha_composite(glow)
    draw = ImageDraw.Draw(img)

    # Header
    enso(draw, [W // 2 - 44, 64, W // 2 + 44, 152], TEAL, width=9)
    glow_dot(draw, (W // 2 + 38, 78), VIOLET, r=5)
    title = "ZenGrowth"
    tf = font(FONT_BOLD, 84)
    draw.text(((W - draw.textlength(title, font=tf)) / 2, 168), title, font=tf, fill=INK)
    tag = "Discover.  Score.  Generate.  Track."
    tgf = font(FONT_REG, 30)
    draw.text(((W - draw.textlength(tag, font=tgf)) / 2, 268), tag, font=tgf, fill=TEAL)

    # Four-stage horizontal pipeline with icons
    stages = [
        ("Discover", "ATS feeds"),
        ("Score", "Claude + EV"),
        ("Generate", "evidence-grounded"),
        ("Track", "audited pipeline"),
    ]
    n = len(stages)
    y = 430
    left, right = 150, W - 150
    xs = [left + (right - left) * i / (n - 1) for i in range(n)]
    for i in range(n - 1):
        grad_line(draw, (xs[i], y), (xs[i + 1], y), TEAL, VIOLET, width=5)

    for i, (head, sub) in enumerate(stages):
        x = xs[i]
        col = lerp(TEAL, VIOLET, i / (n - 1))
        # node chip
        r = 34
        draw.ellipse([x - r, y - r, x + r, y + r], outline=col, width=4,
                     fill=(BG_TOP[0], BG_TOP[1], BG_TOP[2]))
        draw_icon(draw, i, (x, y), col)
        hf = font(FONT_BOLD, 26)
        sf = font(FONT_REG, 19)
        draw.text((x - draw.textlength(head, font=hf) / 2, y + 52), head, font=hf, fill=INK)
        draw.text((x - draw.textlength(sub, font=sf) / 2, y + 86), sub, font=sf, fill=MUTED)

    # Audit thread caption
    af = font(FONT_REG, 21)
    cap = "Every decision written to an audit log"
    draw.text(((W - draw.textlength(cap, font=af)) / 2, 610), cap, font=af, fill=MUTED)

    ARCHIVE.mkdir(exist_ok=True)
    out = ARCHIVE / "poster.png"
    img.convert("RGB").save(out, "PNG")
    return out


def draw_icon(draw: ImageDraw.ImageDraw, idx: int, center, color) -> None:
    cx, cy = center
    if idx == 0:  # magnifier (discover)
        draw.ellipse([cx - 14, cy - 14, cx + 4, cy + 4], outline=color, width=4)
        draw.line([cx + 3, cy + 3, cx + 14, cy + 14], fill=color, width=4)
    elif idx == 1:  # gauge dial (score)
        draw.arc([cx - 15, cy - 12, cx + 15, cy + 18], start=180, end=360, fill=color, width=4)
        ang = math.radians(235)
        draw.line([cx, cy + 3, cx + 13 * math.cos(ang), cy + 3 + 13 * math.sin(ang)],
                  fill=color, width=4)
    elif idx == 2:  # document (generate)
        draw.rectangle([cx - 11, cy - 14, cx + 11, cy + 14], outline=color, width=4)
        for dy in (-5, 1, 7):
            draw.line([cx - 5, cy + dy, cx + 6, cy + dy], fill=color, width=2)
    else:  # kanban board (track)
        for dx in (-12, 0, 12):
            draw.line([cx + dx, cy - 13, cx + dx, cy + 13], fill=color, width=4)


if __name__ == "__main__":
    b = render_banner()
    p = render_poster()
    print("wrote", b)
    print("wrote", p)
