"""Seed the operator's portfolio docs into the knowledge graph.

Ingests every supported file in a directory (default ``docs/career``) as a
knowledge ``SourceDocument`` — so the project-impact write-ups (and the claims and
entities extracted from them) are viewable on ``/knowledge/graph`` and become
reusable evidence for future application materials. Re-run after editing a file to
capture a new version (content-addressed: unchanged files are skipped).

Usage:
    python -m zengrowth.knowledge.seed [directory]   # default: docs/career
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlmodel import Session

from ..config import Settings
from ..db import get_engine, init_db
from .embeddings import EmbeddingClient
from .extractor import KnowledgeExtractionClient
from .parsers import SUPPORTED_EXTENSIONS
from .service import IngestResult, infer_source_type, ingest_path, is_cv_style_upload

DEFAULT_PORTFOLIO_DIR = Path("docs/career")


def seed_documents(
    session: Session,
    directory: str | Path = DEFAULT_PORTFOLIO_DIR,
    *,
    settings: Settings | None = None,
    extractor: KnowledgeExtractionClient | None = None,
    embedder: EmbeddingClient | None = None,
) -> list[IngestResult]:
    """Ingest supported files in ``directory`` (non-recursive) into the knowledge store.

    Mirrors ``import_inbox`` but for an arbitrary directory, so the portfolio can be
    kept in version control and surfaced on the knowledge graph on demand. Embeddings
    follow the global opt-in flag (off by default); extraction uses the configured
    Claude model.
    """
    base = Path(directory)
    results: list[IngestResult] = []
    if not base.exists():
        return results
    for path in sorted(base.iterdir()):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            results.append(
                ingest_path(
                    session,
                    path,
                    source_type=infer_source_type(path),
                    promote_template=is_cv_style_upload(path),
                    settings=settings,
                    extractor=extractor,
                    embedder=embedder,
                )
            )
    return results


def _main(argv: list[str]) -> int:
    directory = Path(argv[1]) if len(argv) >= 2 else DEFAULT_PORTFOLIO_DIR
    if not directory.exists():
        print(f"directory not found: {directory}", file=sys.stderr)
        return 2
    init_db()
    with Session(get_engine()) as session:
        results = seed_documents(session, directory)
    created = sum(1 for r in results if r.created)
    print(
        f"Seeded {len(results)} document(s) from {directory} "
        f"into the knowledge graph ({created} new, {len(results) - created} unchanged)."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
