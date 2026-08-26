"""SQLite engine, session factory, init helper.

`python -m zengrowth.db init` creates the data dir and tables.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings


def _sqlite_path(database_url: str) -> Path | None:
    """Extract a filesystem path from a sqlite:/// URL, else None."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return None
    return Path(database_url[len(prefix):])


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().database_url
    path = _sqlite_path(url)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(url, echo=False, connect_args={"check_same_thread": False})


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
    return _engine


def init_db() -> None:
    # Importing models here so SQLModel.metadata is populated before create_all.
    from . import models  # noqa: F401

    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _migrate_sqlite(engine)


_JOB_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("job_summary", "JSON"),
    ("summary_updated_at", "DATETIME"),
    # Outcome tracking (TA-01).
    ("applied_at", "DATETIME"),
    ("first_response_at", "DATETIME"),
    ("outcome_stage", "VARCHAR"),
    ("outcome_result", "VARCHAR"),
    ("rejection_stage", "VARCHAR"),
    ("outcome_notes", "TEXT"),
    ("outcome_updated_at", "DATETIME"),
)


_GENERATEDMATERIAL_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("draft_json", "JSON"),
    ("version", "INTEGER DEFAULT 1"),
    ("is_final", "BOOLEAN DEFAULT 0"),
    ("supersedes_id", "INTEGER"),
    ("page_count", "INTEGER"),
    ("page_fill", "REAL"),
    # Interview workflow (INT-01).
    ("interview_id", "INTEGER"),
    ("audience", "VARCHAR DEFAULT 'employer'"),
    ("effective_date", "DATETIME"),
)


_SOURCEDOCUMENT_ADDED_COLUMNS: tuple[tuple[str, str], ...] = (
    # Knowledge graph + versioning (paste-to-save / template promotion).
    ("title", "VARCHAR"),
    ("summary", "TEXT"),
    ("lineage_id", "VARCHAR"),
    ("version", "INTEGER DEFAULT 1"),
    ("supersedes_id", "INTEGER"),
    ("is_current", "BOOLEAN DEFAULT 1"),
    ("template_role", "VARCHAR"),
)


def _migrate_sqlite(engine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as conn:
        job_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(job)"))}
        for name, ddl in _JOB_ADDED_COLUMNS:
            if name not in job_cols:
                conn.execute(text(f"ALTER TABLE job ADD COLUMN {name} {ddl}"))
        material_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(generatedmaterial)"))}
        for name, ddl in _GENERATEDMATERIAL_ADDED_COLUMNS:
            if name not in material_cols:
                conn.execute(text(f"ALTER TABLE generatedmaterial ADD COLUMN {name} {ddl}"))
        source_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(sourcedocument)"))}
        for name, ddl in _SOURCEDOCUMENT_ADDED_COLUMNS:
            if name not in source_cols:
                conn.execute(text(f"ALTER TABLE sourcedocument ADD COLUMN {name} {ddl}"))


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def _main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "init":
        init_db()
        tables = sorted(SQLModel.metadata.tables.keys())
        print(f"Initialised {len(tables)} tables: {', '.join(tables)}")
        print(f"DB: {get_settings().database_url}")
        return 0
    print("usage: python -m zengrowth.db init", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
