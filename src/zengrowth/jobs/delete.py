"""Hard-delete jobs and their dependent rows."""

from __future__ import annotations

from sqlmodel import Session, select

from ..audit import log_action
from ..materials.files import delete_material_files
from ..models import (
    ActorType,
    Application,
    GeneratedMaterial,
    Interview,
    Job,
    JobFacet,
    LifecycleState,
)


def delete_job(session: Session, job: Job) -> None:
    """Remove a job, its materials (and files), interviews, and application rows."""
    job_id = job.id
    if job_id is None:
        return

    for material in session.exec(select(GeneratedMaterial).where(GeneratedMaterial.job_id == job_id)):
        delete_material_files(material)
        session.delete(material)

    for interview in session.exec(select(Interview).where(Interview.job_id == job_id)):
        session.delete(interview)

    for application in session.exec(select(Application).where(Application.job_id == job_id)):
        session.delete(application)

    for facet in session.exec(select(JobFacet).where(JobFacet.job_id == job_id)):
        session.delete(facet)

    session.delete(job)


def delete_jobs_by_state(session: Session, state: LifecycleState) -> int:
    jobs = list(session.exec(select(Job).where(Job.lifecycle_state == state)))
    for job in jobs:
        delete_job(session, job)
    if jobs:
        session.commit()
        log_action(
            session,
            actor=ActorType.human,
            action="purge_jobs",
            entity_type="job",
            entity_id=None,
            detail={"lifecycle_state": state.value, "deleted": len(jobs)},
        )
    return len(jobs)
