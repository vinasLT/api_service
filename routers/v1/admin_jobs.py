from datetime import datetime
from typing import Annotated
from AuthTools.Permissions.dependencies import require_permissions
from fastapi import APIRouter, Depends, Query
from rfc9457 import NotFoundProblem
from sqlalchemy.ext.asyncio import AsyncSession

from config import Permissions
from database.crud.job_runs import JobRunsService
from database.db.session import get_async_db
from request_schemas.job_runs import (
    JobDetailOut,
    JobRunDetailOut,
    JobRunsFilterIn,
    JobRunsPageOut,
    JobSummaryOut,
)
from services.job_status import job_summaries, job_summary, run_detail, run_out

admin_jobs_router = APIRouter()

RECENT_RUNS = 20


@admin_jobs_router.get(
    "",
    response_model=list[JobSummaryOut],
    dependencies=[Depends(require_permissions(Permissions.SEO_JOBS))],
    description=f"List job health summaries, required permissions: {Permissions.SEO_JOBS.value}",
)
async def list_job_statuses(db: AsyncSession = Depends(get_async_db)):
    return await job_summaries(JobRunsService(db))


@admin_jobs_router.get(
    "/runs",
    response_model=JobRunsPageOut,
    dependencies=[Depends(require_permissions(Permissions.SEO_JOBS))],
    description=f"List job run history, required permissions: {Permissions.SEO_JOBS.value}",
)
async def list_job_runs(
    job_id: str | None = None,
    status: Annotated[list[str] | None, Query()] = None,
    trigger: str | None = None,
    started_from: datetime | None = None,
    started_to: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: AsyncSession = Depends(get_async_db),
):
    filters = JobRunsFilterIn(
        job_id=job_id,
        status=status or [],
        trigger=trigger,
        started_from=started_from,
        started_to=started_to,
        limit=limit,
        offset=offset,
    )
    total, rows = await JobRunsService(db).list_runs(filters)
    return JobRunsPageOut(total=total, items=[run_out(row) for row in rows])


@admin_jobs_router.get(
    "/runs/{run_id}",
    response_model=JobRunDetailOut,
    dependencies=[Depends(require_permissions(Permissions.SEO_JOBS))],
    description=f"Get a job run with its result and traceback, required permissions: {Permissions.SEO_JOBS.value}",
)
async def get_job_run(run_id: int, db: AsyncSession = Depends(get_async_db)):
    row = await JobRunsService(db).get(run_id)
    if row is None:
        raise NotFoundProblem(detail="Job run not found")
    return run_detail(row)


@admin_jobs_router.get(
    "/{job_id}",
    response_model=JobDetailOut,
    dependencies=[Depends(require_permissions(Permissions.SEO_JOBS))],
    description=f"Get one job's health summary and recent runs, required permissions: {Permissions.SEO_JOBS.value}",
)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_async_db)):
    service = JobRunsService(db)
    summary = await job_summary(service, job_id)
    if summary is None:
        raise NotFoundProblem(detail="Job not found")
    runs = await service.latest_runs(job_id, RECENT_RUNS)
    return JobDetailOut(**summary.model_dump(), runs=[run_out(row) for row in runs])
