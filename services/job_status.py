from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from database.crud.job_runs import JobRunsService
from database.models.job_runs import JobRun
from jobs.job_runs import (
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_RUNNING,
    STATUS_SKIPPED,
    STATUS_SUCCEEDED,
    STATUS_TIMEOUT,
)
from jobs.scheduler import (
    MISFIRE_GRACE_SECONDS,
    SCHEDULER_TIMEZONE,
    JobSpec,
    scheduled_jobs,
)
from request_schemas.job_runs import (
    JobRunDetailOut,
    JobRunOut,
    JobSummaryOut,
    LastRunOut,
    StatusCountsOut,
)

SUCCESS_STATUSES = {STATUS_SUCCEEDED, STATUS_SKIPPED}
FAILURE_STATUSES = {STATUS_FAILED, STATUS_TIMEOUT, STATUS_INTERRUPTED}
FINISHED_STATUSES = SUCCESS_STATUSES | FAILURE_STATUSES
ALL_STATUSES = (
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_SKIPPED,
    STATUS_FAILED,
    STATUS_TIMEOUT,
    STATUS_INTERRUPTED,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; those values were stored as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def error_summary(error: str | None) -> str | None:
    if not error:
        return None
    lines = [line.strip() for line in error.strip().splitlines() if line.strip()]
    return lines[-1] if lines else None


def run_out(row: JobRun) -> JobRunOut:
    return JobRunOut(
        id=row.id,
        job_id=row.job_id,
        trigger=row.trigger,
        status=row.status,
        started_at=as_utc(row.started_at),
        finished_at=as_utc(row.finished_at),
        duration_seconds=row.duration_seconds,
        exit_code=row.exit_code,
        error_summary=error_summary(row.error),
    )


def run_detail(row: JobRun) -> JobRunDetailOut:
    return JobRunDetailOut(**run_out(row).model_dump(), result=row.result, error=row.error)


def job_specs() -> dict[str, JobSpec]:
    timezone = ZoneInfo(SCHEDULER_TIMEZONE)
    return {spec.job_id: spec for spec in scheduled_jobs(timezone)}


def _next_run_at(spec: JobSpec | None, now: datetime) -> datetime | None:
    if spec is None or not spec.enabled or not isinstance(spec.trigger, CronTrigger):
        return None
    return as_utc(spec.trigger.get_next_fire_time(None, now))


def _overdue(spec: JobSpec | None, last_started: datetime | None, now: datetime) -> bool:
    """A cron job is overdue when its next slot after the last run is past the grace window."""
    if (
        spec is None
        or not spec.enabled
        or last_started is None
        or not isinstance(spec.trigger, CronTrigger)
    ):
        return False
    started = as_utc(last_started)
    next_due = spec.trigger.get_next_fire_time(started, started)
    if next_due is None:
        return False
    return now > as_utc(next_due) + timedelta(seconds=MISFIRE_GRACE_SECONDS)


async def summarize(
    service: JobRunsService, job_id: str, spec: JobSpec | None, now: datetime
) -> JobSummaryOut:
    latest = await service.latest(job_id)
    latest_finished = await service.last_with_status(job_id, FINISHED_STATUSES)
    last_success = await service.last_with_status(job_id, SUCCESS_STATUSES)
    last_failure = await service.last_with_status(job_id, FAILURE_STATUSES)
    success_at = as_utc(last_success.started_at) if last_success is not None else None
    consecutive_failures = await service.count_since(job_id, FAILURE_STATUSES, success_at)
    counts = await service.counts_by_status(job_id, now - timedelta(hours=24))
    overdue = _overdue(spec, latest.started_at if latest is not None else None, now)
    latest_was_success = (
        latest_finished is not None and latest_finished.status in SUCCESS_STATUSES
    )

    return JobSummaryOut(
        job_id=job_id,
        scheduled=spec is not None,
        enabled=spec.enabled if spec is not None else False,
        schedule=spec.schedule if spec is not None else None,
        timeout_seconds=spec.timeout if spec is not None else None,
        running=latest is not None and latest.status == STATUS_RUNNING,
        healthy=latest_was_success and not overdue,
        overdue=overdue,
        consecutive_failures=consecutive_failures,
        last_success_at=as_utc(last_success.finished_at) if last_success else None,
        last_failure_at=as_utc(last_failure.finished_at) if last_failure else None,
        next_run_at=_next_run_at(spec, now),
        last_run=_last_run(latest),
        last_24h=StatusCountsOut(**{status: counts.get(status, 0) for status in ALL_STATUSES}),
    )


async def job_summaries(service: JobRunsService) -> list[JobSummaryOut]:
    specs = job_specs()
    extra = sorted(job_id for job_id in await service.job_ids() if job_id not in specs)
    now = _now()
    summaries = [
        await summarize(service, spec.job_id, spec, now) for spec in specs.values()
    ]
    summaries.extend(
        [await summarize(service, job_id, None, now) for job_id in extra]
    )
    return summaries


async def job_summary(service: JobRunsService, job_id: str) -> JobSummaryOut | None:
    spec = job_specs().get(job_id)
    if spec is None and await service.latest(job_id) is None:
        return None
    return await summarize(service, job_id, spec, _now())


def _last_run(row: JobRun | None) -> LastRunOut | None:
    if row is None:
        return None
    return LastRunOut(
        id=row.id,
        status=row.status,
        started_at=as_utc(row.started_at),
        finished_at=as_utc(row.finished_at),
        duration_seconds=row.duration_seconds,
        exit_code=row.exit_code,
    )
