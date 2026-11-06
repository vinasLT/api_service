import asyncio
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from itertools import islice

import httpx
from sqlalchemy import tuple_, update
from sqlalchemy.ext.asyncio import AsyncEngine

from auction_api.api import AuctionApiClient
from auction_api.types.db_lot import DBDeleteLot, DBUpdateLot
from core.logger import logger
from database.db.session import AsyncSessionLocal, engine_async
from database.models.saved_lots import SavedLots
from jobs.common import has_saved_lots, run_job
from jobs.locks import SAVED_LOTS_WRITE_LOCK, advisory_lock
from jobs.saved_lots_upsert import (
    MAX_CONCURRENT_SAVES,
    create_save_engine,
    save_lots,
)
from request_schemas.db_save_schemas import DBCurrentDeleteIn, DBCurrentUpdateIn

PAGE_SIZE = 1000
MAX_IN_FLIGHT_PAGES = 6
SQLITE_MAX_BIND_PARAMETERS = 900
# The update feed rejects a date_from older than 3 days. Three calendar days
# back is already past that limit once the API reads it as midnight.
UPDATED_LOT_LOOKBACK_DAYS = 2
DELETED_LOT_LOOKBACK_DAYS = 3


def _get_date_range(lookback_days: int, now: datetime | None = None) -> tuple[str, str]:
    current = now or datetime.now(tz=timezone.utc)
    date_from = (current - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    date_to = current.strftime("%Y-%m-%d")
    return date_from, date_to


async def _fetch_deleted_lots(
    api: AuctionApiClient, date_from: str, date_to: str
) -> list[DBDeleteLot]:
    request = DBCurrentDeleteIn(date_from=date_from, date_to=date_to)
    response = await api.request_with_schema(api.GET_DB_DELETED_LOTS, request)
    return response.data


async def _mark_deleted_lots(
    lots: Iterable[DBDeleteLot],
) -> tuple[set[tuple[str, int]], int]:
    deleted_keys = {(str(lot.lot_id), lot.site) for lot in lots}
    if not deleted_keys:
        return deleted_keys, 0

    deleted_at = datetime.now(timezone.utc)
    marked_count = 0
    deleted_key_iterator = iter(deleted_keys)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            while batch := list(
                islice(deleted_key_iterator, SQLITE_MAX_BIND_PARAMETERS // 2)
            ):
                result = await session.execute(
                    update(SavedLots)
                    .where(
                        tuple_(SavedLots.lot_id, SavedLots.site).in_(batch),
                        SavedLots.is_deleted.is_(False),
                    )
                    .values(is_deleted=True, deleted_at=deleted_at)
                )
                marked_count += result.rowcount or 0
    return deleted_keys, marked_count


async def _fetch_all_updated_lots(
    api: AuctionApiClient,
    date_from: str,
    date_to: str,
    deleted_keys: set[tuple[str, int]],
    save_engine: AsyncEngine,
) -> tuple[int, int]:
    logger.info("Fetching updated lots from {} to {}", date_from, date_to)

    request = DBCurrentUpdateIn.model_validate(
        {
            "date_from": date_from,
            "date_to": date_to,
            "page": 1,
            "size": PAGE_SIZE,
        }
    )
    first_page = await api.request_with_schema(api.GET_DB_UPDATED_LOTS, request)
    total_pages = first_page.pages
    first_lots = first_page.data
    del first_page
    logger.info("Updated-lot feed has {} pages", total_pages)

    async def fetch_page(page: int) -> list[DBUpdateLot]:
        page_request = request.model_copy(update={"page": page})
        response = await api.request_with_schema(api.GET_DB_UPDATED_LOTS, page_request)
        return response.data

    in_flight = asyncio.Semaphore(MAX_IN_FLIGHT_PAGES)
    save_slots = asyncio.Semaphore(MAX_CONCURRENT_SAVES)
    progress_lock = asyncio.Lock()
    fetched_count = 0
    saved_count = 0
    completed_pages = 0

    async def process_page(page: int, lots: list[DBUpdateLot] | None = None) -> None:
        nonlocal fetched_count, saved_count, completed_pages
        try:
            async with in_flight:
                if lots is None:
                    lots = await fetch_page(page)
                page_fetched = len(lots)
                async with save_slots:
                    page_saved = await save_lots(lots, deleted_keys, save_engine)
                del lots
        except Exception:
            logger.exception("Failed to process updated-lot page {}", page)
            raise

        async with progress_lock:
            fetched_count += page_fetched
            saved_count += page_saved
            completed_pages += 1
            if (
                completed_pages == 1
                or completed_pages % 10 == 0
                or completed_pages == total_pages
            ):
                logger.info(
                    "Processed {}/{} pages: fetched {}, saved {} lots",
                    completed_pages,
                    total_pages,
                    fetched_count,
                    saved_count,
                )

    tasks = [asyncio.create_task(process_page(1, first_lots))]
    del first_lots
    tasks.extend(
        asyncio.create_task(process_page(page)) for page in range(2, total_pages + 1)
    )
    try:
        await asyncio.gather(*tasks)
    except Exception:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return fetched_count, saved_count


async def _sync() -> dict:
    deleted_from, deleted_to = _get_date_range(DELETED_LOT_LOOKBACK_DAYS)
    updated_from, updated_to = _get_date_range(UPDATED_LOT_LOOKBACK_DAYS)
    logger.info(
        "Starting lot sync; deleted lots {} through {}, updated lots {} through {}",
        deleted_from,
        deleted_to,
        updated_from,
        updated_to,
    )
    save_engine = create_save_engine()
    try:
        async with httpx.AsyncClient(timeout=60.0) as http_client:
            api = AuctionApiClient()
            api._http_client = http_client

            deleted_lots = await _fetch_deleted_lots(api, deleted_from, deleted_to)
            deleted_keys, marked_count = await _mark_deleted_lots(deleted_lots)
            logger.info(
                "Processed {} deleted-lot records; marked {} saved lots as deleted",
                len(deleted_lots),
                marked_count,
            )
            del deleted_lots

            fetched_count, saved_count = await _fetch_all_updated_lots(
                api, updated_from, updated_to, deleted_keys, save_engine
            )
            return {
                "deleted_count": marked_count,
                "deleted_keys_count": len(deleted_keys),
                "fetched_count": fetched_count,
                "saved_count": saved_count,
            }
    finally:
        await save_engine.dispose()


async def run() -> dict:
    async with advisory_lock(engine_async, SAVED_LOTS_WRITE_LOCK) as acquired:
        if not acquired:
            logger.warning("Lot sync skipped: another saved_lots writer is running")
            return {"skipped": "lock_held"}
        if not await has_saved_lots():
            logger.warning("Lot sync skipped: saved_lots is empty, waiting for bootstrap")
            return {"skipped": "not_bootstrapped"}
        return await _sync()


def main() -> None:
    run_job("lots_sync", run)


if __name__ == "__main__":
    main()
