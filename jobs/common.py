import asyncio
import os
import sys
import time
import traceback
from collections.abc import Awaitable, Callable

from sqlalchemy import exists, func, select

import jobs.job_runs as job_runs
from core.logger import logger
from database.db.session import AsyncSessionLocal, engine_async
from database.models.saved_lots import SavedLots


async def has_saved_lots() -> bool:
    async with AsyncSessionLocal() as session:
        return bool(await session.scalar(select(exists().where(SavedLots.id.is_not(None)))))


async def count_active_lots() -> int:
    async with AsyncSessionLocal() as session:
        return await session.scalar(
            select(func.count()).select_from(SavedLots).where(SavedLots.is_deleted.is_(False))
        ) or 0


def _scheduled_run_id() -> int | None:
    raw = os.environ.get(job_runs.JOB_RUN_ID_ENV)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring invalid {}: {}", job_runs.JOB_RUN_ID_ENV, raw)
        return None


def run_job(name: str, job: Callable[[], Awaitable[dict]]) -> None:
    """Run an async job as a process entry point: exit 0 on success, 1 on failure."""
    started_at = time.perf_counter()
    scheduled_run_id = _scheduled_run_id()
    manual = scheduled_run_id is None
    run_id = job_runs.start_run(name, job_runs.TRIGGER_MANUAL) if manual else scheduled_run_id

    async def run() -> dict:
        try:
            return await job()
        finally:
            await engine_async.dispose()

    exit_code = 0
    try:
        result = asyncio.run(run())
        job_runs.record_outcome(run_id, result=result)
        logger.info(f"{name} finished", extra={"job": name, "result": result})
    except Exception:
        logger.exception(f"{name} failed", extra={"job": name})
        job_runs.record_outcome(run_id, error=traceback.format_exc())
        exit_code = 1
    finally:
        duration = time.perf_counter() - started_at
        if manual:
            job_runs.finish_run(run_id, exit_code, timed_out=False, duration=duration)
        logger.info(
            f"{name} process finished in {duration:.3f} seconds",
            extra={"job": name, "exit_code": exit_code},
        )
    sys.exit(exit_code)
