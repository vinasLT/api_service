from fastapi import APIRouter, Query, Depends
from fastapi_cache import default_key_builder
from fastapi_cache.decorator import cache
from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicLot, BasicHistoryLot
from auction_api.types.search import BasicManyCurrentLots, CurrentSearchParams
from auction_api.utils import get_lot_vin_or_lot_id
from core.logger import logger
from database.db.session import get_async_db
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import LotByIDIn, LotByVINIn, CurrentBidOut
from schemas.vin_or_lot import VinOrLotIn
from services.transform_slugs import transform_slugs

cars_router = APIRouter()

@cars_router.get("/vin-or-lot-id", response_model=list[BasicLot] | list[BasicHistoryLot] | BasicLot | BasicHistoryLot,
                 description='Get lot by vin or lot id')
@cache(expire=60*30, key_builder=default_key_builder)
async def get_by_lot_id_or_vin(
    data: VinOrLotIn = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug('New request to get lot by vin or lot', extra={'data': data.model_dump()})

    vin_or_lot = data.vin_or_lot.replace(" ", "").upper()
    print(vin_or_lot)
    print(data.site)

    return await get_lot_vin_or_lot_id(api, data.site, vin_or_lot)

@cars_router.get("/current-bid", response_model=CurrentBidOut, description='Get current bid for lot by its lot_id')
@cache(expire=60*10, key_builder=default_key_builder)
async def get_current_bid(data: LotByIDIn = Query(),
                          api: AuctionApiClient = Depends(get_auction_api_service),):
    logger.debug('New request to get current bid by lot id', extra={'data': data.model_dump()})
    return await api.request_with_schema(api.GET_CURRENT_BID_FOR_LOT, data)


@cars_router.get("", response_model=BasicManyCurrentLots)
@cache(expire=60*60, key_builder=default_key_builder)
async def get_current_lots(api: AuctionApiClient = Depends(get_auction_api_service),
                           db: AsyncSession = Depends(get_async_db),
                           search_params: CurrentSearchParams = Query(...)):
    data = await transform_slugs(search_params, db)
    logger.debug('New request to get many current lots', extra={'data': data.model_dump()})
    return await api.request_with_schema(api.GET_CURRENT_LOTS, search_params)


