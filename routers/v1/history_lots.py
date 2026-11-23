from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicHistoryLot
from auction_api.types.search import BasicManyHistoryLot, HistorySearchParams
from core.logger import logger
from database.db.session import get_async_db
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import LotByIDIn, LotByVINIn
from services.provider_cache import (
    TTL_HISTORY_CARS_LISTING,
    cached_provider_call,
    sale_history_ttl,
)
from services.saved_lots_read import (
    ensure_sale_history,
    find_saved_lot,
    find_saved_lots_by_vin,
    saved_lot_to_model,
    site_number,
    store_archival_lots,
)
from services.transform_slugs import transform_slugs

history_cars_router = APIRouter()
HISTORY_PAGE_SIZE_CAP = 25


@history_cars_router.get(
    "/vin",
    response_model=BasicHistoryLot | list[BasicHistoryLot],
    description="Get history lot by vin",
)
async def get_history_by_vin(
    data: LotByVINIn = Query(...),
    db: AsyncSession = Depends(get_async_db),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug("New request to get history lot by vin", extra={"data": data.model_dump(mode="json")})
    rows = await find_saved_lots_by_vin(db, data.vin)
    site_num = site_number(data.site)
    if site_num is not None:
        rows = [row for row in rows if row.site == site_num]
    if rows:
        return [saved_lot_to_model(row) for row in rows]

    result = await cached_provider_call(
        api,
        AuctionApiClient.GET_LOT_HISTORY_BY_VIN,
        data,
        ttl=sale_history_ttl,
    )
    await store_archival_lots(db, result)
    return result


@history_cars_router.get(
    "/lot-id",
    response_model=BasicHistoryLot,
    description="Get history lot by lot id",
)
async def get_history_by_lot_id(
    data: LotByIDIn = Query(...),
    db: AsyncSession = Depends(get_async_db),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug("New request to get history lot by lot id", extra={"data": data.model_dump(mode="json")})
    row = await find_saved_lot(db, data.lot_id, data.site)
    if row is not None:
        if row.is_deleted and row.sale_history_fetched_at is None:
            row = await ensure_sale_history(db, api, row)
        return saved_lot_to_model(row)

    result = await cached_provider_call(
        api,
        AuctionApiClient.GET_LOT_HISTORY_BY_ID,
        data,
        ttl=sale_history_ttl,
    )
    await store_archival_lots(db, result)
    return result


@history_cars_router.get("", response_model=BasicManyHistoryLot, description="Get history lots")
async def get_history_lots(
    data: HistorySearchParams = Query(...),
    db: AsyncSession = Depends(get_async_db),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    data = await transform_slugs(data, db)
    if data.size is not None and data.size > HISTORY_PAGE_SIZE_CAP:
        data.size = HISTORY_PAGE_SIZE_CAP
    logger.debug("New request to get many history lots", extra={"data": data.model_dump(mode="json")})
    return await cached_provider_call(
        api,
        AuctionApiClient.GET_HISTORY_LOTS,
        data,
        ttl=TTL_HISTORY_CARS_LISTING,
    )
