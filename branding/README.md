# Branding assets

Visual assets referenced by the top-level [`README.md`](../README.md).

| File | Used as |
|---|---|
| `logo.png` | Hero image at the top of the README (landscape, page-filling) |
| `poster.png` | Promotional poster lower in the README (landscape, page-filling) |

These are the current main assets. The earlier programmatic graphics live in
[`archive/`](archive) and are no longer referenced.

## Palette

Slate/indigo base (`#0F1426` → `#1E1B3C`) with a teal (`#2DD4BF`) to violet
(`#8B7AFF`) accent and an ensō (zen circle) mark.

## Archive

[`archive/banner.png`](archive/banner.png) and
[`archive/poster.png`](archive/poster.png) are the retired programmatic assets.
They can be regenerated with the legacy script, which now writes straight into
`archive/` so it never overwrites the current mains:

```bash
poetry run python branding/generate_assets.py
```

Requires the Poetry dev dependencies, including Pillow.
