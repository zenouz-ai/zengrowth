# ZenGrowth API image (local-first).
#
# Builds the FastAPI backend with a LaTeX toolchain so material generation can
# compile PDFs. The dashboard is run separately with Vite during local dev
# (see docs/LOCAL_SETUP.md); this image serves the internal-only API on :8000.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.3.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      curl \
      latexmk \
      texlive-latex-extra \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Vendor the small fontawesome (FA4) LaTeX package from CTAN rather than the
# multi-GB texlive-fonts-extra, so uploaded CV styles that use
# \usepackage{fontawesome} compile. Files are placed into TEXMFLOCAL (TDS layout).
RUN curl -fsSL https://mirrors.ctan.org/fonts/fontawesome.zip -o /tmp/fa.zip \
 && python3 -m zipfile -e /tmp/fa.zip /tmp/fa \
 && TL=/usr/local/share/texmf \
 && mkdir -p "$TL/tex/latex/fontawesome" \
            "$TL/fonts/map/dvips/fontawesome" \
            "$TL/fonts/enc/dvips/fontawesome" \
            "$TL/fonts/opentype/public/fontawesome" \
            "$TL/fonts/type1/public/fontawesome" \
            "$TL/fonts/tfm/public/fontawesome" \
 && cp /tmp/fa/fontawesome/tex/*                    "$TL/tex/latex/fontawesome/" \
 && cp /tmp/fa/fontawesome/map/fontawesome.map      "$TL/fonts/map/dvips/fontawesome/" \
 && cp /tmp/fa/fontawesome/enc/*.enc                "$TL/fonts/enc/dvips/fontawesome/" \
 && cp /tmp/fa/fontawesome/opentype/FontAwesome.otf "$TL/fonts/opentype/public/fontawesome/" \
 && cp /tmp/fa/fontawesome/type1/FontAwesome.pfb    "$TL/fonts/type1/public/fontawesome/" \
 && cp /tmp/fa/fontawesome/tfm/*.tfm                "$TL/fonts/tfm/public/fontawesome/" \
 && mktexlsr \
 && updmap-sys --enable Map=fontawesome.map \
 && rm -rf /tmp/fa /tmp/fa.zip

WORKDIR /app

COPY pyproject.toml poetry.lock* README.md ./
RUN poetry install --no-root --without dev

COPY src/ ./src/
COPY templates/ ./templates/
# Synthetic CV template + evidence bank: the material generator falls back to
# docs/career/processed/{cv_source.tex,source_of_truth.md} when no promoted
# template / verified DB claims exist, so the image needs them for CV and
# cover-letter generation to work out of the box. These are synthetic fixtures
# (candidate "Jordan Avery"); real career data is never part of this mirror.
COPY docs/career/processed/ ./docs/career/processed/
RUN poetry install --only-root

EXPOSE 8000

CMD ["uvicorn", "zengrowth.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
