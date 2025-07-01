from contextlib import asynccontextmanager
from typing import List, Optional, Union

import redis
import uvicorn
from fastapi import FastAPI, Request, Query, Depends
from fastapi_cache import FastAPICache, default_key_builder
from fastapi_cache.backends.redis import RedisBackend
from starlette.responses import JSONResponse

from fastapi_cache.decorator import cache

from auction_api.api import AuctionApiClient
from auction_api.types import BasicLot, BasicHistoryLot, LotByIDIn, LotByVINIn, CurrentBidOut
from config import REDIS_URL
from exptions import BadRequestException
from schemas.vin_or_lot import VinOrLotIn

api: AuctionApiClient | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global api
    api = AuctionApiClient()
    redis_client = redis.Redis.from_url(REDIS_URL)
    FastAPICache.init(RedisBackend(redis_client), prefix="fastapi-cache")
    yield

app = FastAPI(lifespan=lifespan)

@app.exception_handler(BadRequestException)
async def bad_request_exception_handler(request: Request, exc: BadRequestException):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message, "code": exc.short_message},
    )



@app.get("/cars/", response_model=List[BasicLot] | List[BasicHistoryLot])
@cache(expire=60*60*24, key_builder=default_key_builder)
async def get_by_lot_id_or_vin(
    site: Optional[Union[int, str]] = Query(None),
    vin_or_lot: str = Query(...),
):
    data = VinOrLotIn(site=site, vin_or_lot=vin_or_lot)

    vin_or_lots = data.vin_or_lot.replace(" ", "").upper()

    if vin_or_lots.isdigit():
        in_data = LotByIDIn(lot_id=int(vin_or_lots), site=data.site)
        return await api.request_with_schema(api.GET_LOT_BY_ID_FOR_ALL_TIME, in_data)
    else:
        in_data = LotByVINIn(vin=vin_or_lots, site=data.site)
        return await api.request_with_schema(api.GET_LOT_BY_VIN_FOR_ALL_TIME, in_data)

@app.get("/cars/current-bid/", response_model=CurrentBidOut)
@cache(expire=60*60*24, key_builder=default_key_builder)
async def get_current_bid(data: LotByIDIn = Query()):
    return await api.request_with_schema(api.GET_CURRENT_BID_FOR_LOT, data)

@app.get("/cars/history/vin/", response_model=BasicHistoryLot)
@cache(expire=60*60*24, key_builder=default_key_builder)
async def get_history_by_vin(vin: str = Query(...), site: str = Query(...)):
    data = LotByVINIn(vin=vin, site=site)
    return await api.request_with_schema(AuctionApiClient.GET_LOT_HISTORY_BY_VIN, data)

@app.get("/cars/history/lot-id/", response_model=BasicHistoryLot)
@cache(expire=60*60*24, key_builder=default_key_builder)
async def get_history_by_vin(lot_id: int = Query(...), site: str = Query(...)):
    data = LotByIDIn(lot_id=lot_id, site=site)
    return await api.request_with_schema(AuctionApiClient.GET_LOT_HISTORY_BY_ID, data)




if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)




