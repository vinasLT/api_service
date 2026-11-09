from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from core.logger import logger
from database.db.session import engine as default_engine
from database.models.job_runs import JobRun

JOB_RUN_ID_ENV = "JOB_RUN_ID"

STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_TIMEOUT = "timeout"
STATUS_INTERRUPTED = "interrupted"

TRIGGER_SCHEDULED = "scheduled"
TRIGGER_MANUAL = "manual"

# Tests replace this with their own engine. Helpers read it at call time.
db_engine: Engine = default_engine


def _bind(engine: Engine | None) -> Engine:
    return db_engine if engine is None else engine


def _final_status(exit_code: int | None, timed_out: bool, result: object) -> str:
    if timed_out:
        return STATUS_TIMEOUT
    if exit_code != 0:
        return STATUS_FAILED
    if isinstance(result, dict) and "skipped" in result:
        return STATUS_SKIPPED
    return STATUS_SUCCEEDED


def start_run(job_id: str, trigger: str, engine: Engine | None = None) -> int | None:
    """Insert a running row. Returns None when recording fails, so the job still runs."""
    try:
        with Session(_bind(engine)) as session:
            row = JobRun(
                job_id=job_id,
                trigger=trigger,
                status=STATUS_RUNNING,
                started_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            return row.id
    except Exception:
        logger.exception("Failed to record job run start for {}", job_id)
        return None


def record_outcome(
    run_id: int | None,
    result: dict | None = None,
    error: str | None = None,
    engine: Engine | None = None,
) -> None:
    """Store the result or traceback the child process knows about."""
    if run_id is None:
        return
    status = STATUS_FAILED if error else _final_status(0, False, result)
    try:
        with Session(_bind(engine)) as session:
            session.execute(
                update(JobRun)
                .where(JobRun.id == run_id)
                .values(status=status, result=result, error=error)
            )
            session.commit()
    except Exception:
        logger.exception("Failed to record job run outcome for run {}", run_id)


def finish_run(
    run_id: int | None,
    exit_code: int | None,
    timed_out: bool,
    duration: float,
    engine: Engine | None = None,
) -> None:
    """Set the final status. A timeout overrides whatever the child recorded."""
    if run_id is None:
        return
    try:
        with Session(_bind(engine)) as session:
            result = session.scalar(select(JobRun.result).where(JobRun.id == run_id))
            session.execute(
                update(JobRun)
                .where(JobRun.id == run_id)
                .values(
                    status=_final_status(exit_code, timed_out, result),
                    finished_at=datetime.now(timezone.utc),
                    duration_seconds=duration,
                    exit_code=exit_code,
                )
            )
            session.commit()
    except Exception:
        logger.exception("Failed to finish job run {}", run_id)


def mark_interrupted(engine: Engine | None = None) -> int | None:
    """Rows still running belong to a scheduler process that died."""
    try:
        with Session(_bind(engine)) as session:
            result = session.execute(
                update(JobRun)
                .where(JobRun.status == STATUS_RUNNING)
                .values(
                    status=STATUS_INTERRUPTED,
                    finished_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            return result.rowcount
    except Exception:
        logger.exception("Failed to mark interrupted job runs")
        return None


def prune(older_than_days: int, engine: Engine | None = None) -> int | None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    try:
        with Session(_bind(engine)) as session:
            result = session.execute(delete(JobRun).where(JobRun.started_at < cutoff))
            session.commit()
            return result.rowcount
    except Exception:
        logger.exception("Failed to prune job runs")
        return None
