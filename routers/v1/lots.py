from fastapi import APIRouter, Query, Depends
from fastapi_cache import default_key_builder
from fastapi_cache.decorator import cache

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicLot, BasicHistoryLot
from auction_api.types.search import BasicManyCurrentLots, CurrentSearchParams
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import LotByIDIn, LotByVINIn, CurrentBidOut
from schemas.vin_or_lot import VinOrLotIn

cars_router = APIRouter()

@cars_router.get("/vin-or-lot-id", response_model=list[BasicLot] | list[BasicHistoryLot],
                 description='Get lot by vin or lot id')
@cache(expire=60*30, key_builder=default_key_builder)
async def get_by_lot_id_or_vin(
    data: VinOrLotIn = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
):

    vin_or_lots = data.vin_or_lot.replace(" ", "").upper()

    if vin_or_lots.isdigit():
        in_data = LotByIDIn(site=data.site, lot_id=int(data.vin_or_lot))
        return await api.request_with_schema(api.GET_LOT_BY_ID_FOR_ALL_TIME, in_data, lot_id=in_data.lot_id)
    else:
        in_data = LotByVINIn(vin=vin_or_lots, site=data.site)
        return await api.request_with_schema(api.GET_LOT_BY_VIN_FOR_ALL_TIME, in_data)

@cars_router.get("/current-bid", response_model=CurrentBidOut, description='Get current bid for lot by its lot_id')
@cache(expire=60*10, key_builder=default_key_builder)
async def get_current_bid(data: LotByIDIn = Query(),
                          api: AuctionApiClient = Depends(get_auction_api_service),):
    return await api.request_with_schema(api.GET_CURRENT_BID_FOR_LOT, data)


@cars_router.get("", response_model=BasicManyCurrentLots)
@cache(expire=60*60, key_builder=default_key_builder)
async def get_current_lots(api: AuctionApiClient = Depends(get_auction_api_service),
                           search_params: CurrentSearchParams = Query(...)):

    return await api.request_with_schema(api.GET_CURRENT_LOTS, search_params)


