from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicHistoryLot
from database.db.session import get_async_db
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import LotByIDIn
from schemas.sale_history import SaleHistoryOut
from services.provider_cache import cached_provider_call, sale_history_ttl
from services.saved_lots_read import (
    ensure_sale_history,
    find_saved_lot,
    sales_from_history,
    sales_from_row,
    store_archival_lots,
)

sales_history_router = APIRouter()


@sales_history_router.get("", response_model=list[SaleHistoryOut], description="Get sales history by lot id")
async def get_sales_history(
    data: LotByIDIn = Query(...),
    db: AsyncSession = Depends(get_async_db),
    api: AuctionApiClient = Depends(get_auction_api_service),
) -> list[SaleHistoryOut]:
    row = await find_saved_lot(db, data.lot_id, data.site)
    if row is not None:
        if row.is_deleted and row.sale_history_fetched_at is None:
            row = await ensure_sale_history(db, api, row)
        return sales_from_row(row)

    result: BasicHistoryLot = await cached_provider_call(
        api,
        AuctionApiClient.GET_LOT_HISTORY_BY_ID,
        data,
        ttl=sale_history_ttl,
    )
    await store_archival_lots(db, result)
    return sales_from_history(result)
