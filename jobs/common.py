import asyncio
import sys
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import exists, func, select

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


def run_job(name: str, job: Callable[[], Awaitable[dict]]) -> None:
    """Run an async job as a process entry point: exit 0 on success, 1 on failure."""
    started_at = time.perf_counter()

    async def run() -> dict:
        try:
            return await job()
        finally:
            await engine_async.dispose()

    exit_code = 0
    try:
        result = asyncio.run(run())
        logger.info(f"{name} finished", extra={"job": name, "result": result})
    except Exception:
        logger.exception(f"{name} failed", extra={"job": name})
        exit_code = 1
    finally:
        logger.info(
            f"{name} process finished in {time.perf_counter() - started_at:.3f} seconds",
            extra={"job": name, "exit_code": exit_code},
        )
    sys.exit(exit_code)
