from fastapi import APIRouter, Depends, Query
from rfc9457 import NotFoundProblem
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicHistoryLot
from database.db.session import get_async_db
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import LotByIDIn
from services.saved_lots_read import ensure_sale_history, find_saved_lot, saved_lot_to_model

saved_lots_router = APIRouter()


@saved_lots_router.get(
    "/saved",
    response_model=BasicHistoryLot,
    description="Indexed lot from saved_lots, including sold lots. Sale history is fetched once.",
)
async def get_saved_lot(
    data: LotByIDIn = Query(...),
    db: AsyncSession = Depends(get_async_db),
    api: AuctionApiClient = Depends(get_auction_api_service),
) -> BasicHistoryLot:
    row = await find_saved_lot(db, data.lot_id, data.site)
    if row is None:
        raise NotFoundProblem(detail="Lot not found")
    if row.is_deleted and row.sale_history_fetched_at is None:
        row = await ensure_sale_history(db, api, row)
    return saved_lot_to_model(row)
