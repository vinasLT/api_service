from contextlib import asynccontextmanager
from typing import List

import uvicorn
from fastapi import FastAPI, Request, Query
from starlette.responses import JSONResponse

from fastapi_cache.decorator import cache
from vinas_external_api_app.src.vinas_external_api_app.auction_api.api import AuctionApiClient
from vinas_external_api_app.src.vinas_external_api_app.auction_api.types import LotByIDIn, BasicLot, LotByVINIn, \
    BasicHistoryLot, CurrentBidOut
from vinas_external_api_app.src.vinas_external_api_app.exptions import BadRequestException
from vinas_external_api_app.src.vinas_external_api_app.schemas.vin_or_lot import VinOrLotIn

api: AuctionApiClient | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global api
    api = AuctionApiClient()
    yield

app = FastAPI(lifespan=lifespan)

@app.exception_handler(BadRequestException)
async def bad_request_exception_handler(request: Request, exc: BadRequestException):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.message, "code": exc.short_message},
    )



@app.get("/cars/", response_model=List[BasicLot] | List[BasicHistoryLot])
@cache(expire=60*30)
async def get_by_lot_id_or_vin(data: VinOrLotIn = Query(...)):
    vin_or_lot = data.vin_or_lot
    vin_or_lots = vin_or_lot.replace(" ", "").upper()

    if vin_or_lots.isdigit():
        in_data = LotByIDIn(lot_id=int(vin_or_lots), site=data.site)
        return await api.request_with_schema(api.GET_LOT_BY_ID_FOR_ALL_TIME, in_data)
    else:
        in_data = LotByVINIn(vin=vin_or_lots, site=data.site)
        return await api.request_with_schema(api.GET_LOT_BY_VIN_FOR_ALL_TIME, in_data)

@app.get("/cars/current-bid/", response_model=CurrentBidOut)
@cache(expire=60*10)
async def get_current_bid(data: LotByIDIn = Query(...)):
    return await api.request_with_schema(api.GET_CURRENT_BID_FOR_LOT, data)


if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8000)




