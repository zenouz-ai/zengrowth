"""Retention purge for superseded material versions."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, select

from ..audit import log_action
from ..config import get_settings
from ..db import get_engine, init_db
from ..models import ActorType, GeneratedMaterial
from .files import delete_material_files


def _keeper(materials: list[GeneratedMaterial]) -> GeneratedMaterial:
    finals = [material for material in materials if material.is_final]
    if finals:
        return max(finals, key=lambda material: (material.version, material.created_at))
    return max(materials, key=lambda material: (material.version, material.created_at))


def purge_old_material_versions(
    session: Session,
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
) -> list[int]:
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.materials_retention_days
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    # Interview-scoped artifacts group per round: interview A's latest debrief
    # must not mark interview B's debrief as a superseded version (INT-01).
    grouped: dict[tuple[int, str, int | None], list[GeneratedMaterial]] = defaultdict(list)
    for material in session.exec(select(GeneratedMaterial)).all():
        grouped[(material.job_id, material.material_type, material.interview_id)].append(material)

    purged: list[int] = []
    for (_job_id, _material_type, _interview_id), materials in grouped.items():
        if len(materials) <= 1:
            continue
        keeper = _keeper(materials)
        for material in materials:
            if material.id == keeper.id:
                continue
            created = material.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if created >= cutoff:
                continue
            delete_material_files(material)
            session.delete(material)
            purged.append(material.id or 0)
            log_action(
                session,
                actor=ActorType.system,
                action="purge_material_version",
                entity_type="job",
                entity_id=material.job_id,
                detail={
                    "material_id": material.id,
                    "version": material.version,
                    "kept_id": keeper.id,
                    "material_type": material.material_type,
                },
            )
    if purged:
        session.commit()
    return purged


def _main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "purge":
        init_db()
        with Session(get_engine()) as session:
            purged = purge_old_material_versions(session)
        print(f"Purged {len(purged)} material version(s).")
        return 0
    print("usage: python -m zengrowth.materials.retention purge", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
