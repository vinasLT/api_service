from fastapi import APIRouter, Depends, Query

from auction_api.api import AuctionApiClient
from auction_api.types.search import BasicManyHistoryLot, HistorySearchParams
from core.logger import logger
from dependencies.auction_api_service import get_auction_api_service
from schemas.similar_archived_sales import SimilarArchivedSalesPricesOut
from schemas.similar_history_lots import SimilarHistoryLots
from services.provider_cache import TTL_HISTORY_CARS_SIMILAR, cached_provider_call

similar_sales_router = APIRouter()


def _build_history_search_params(data: SimilarHistoryLots) -> HistorySearchParams:
    year_from = data.year - 5 if data.year is not None else None
    year_to = data.year + 5 if data.year is not None else None
    return HistorySearchParams(
        make=data.make,
        model=data.model,
        year_from=year_from,
        year_to=year_to,
        vehicle_type=data.vehicle_type,
        site=data.site,
    )


async def _similar_history(api: AuctionApiClient, data: SimilarHistoryLots) -> BasicManyHistoryLot:
    params = _build_history_search_params(data)
    return await cached_provider_call(
        api,
        AuctionApiClient.GET_HISTORY_LOTS,
        params,
        ttl=TTL_HISTORY_CARS_SIMILAR,
    )


@similar_sales_router.get("", response_model=BasicManyHistoryLot)
async def get_similar_sales(
    data: SimilarHistoryLots = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug("New request to get many history lots", extra={"data": data.model_dump()})
    return await _similar_history(api, data)


@similar_sales_router.get("/prices", response_model=SimilarArchivedSalesPricesOut)
async def get_similar_sales_prices(
    data: SimilarHistoryLots = Query(...),
    api: AuctionApiClient = Depends(get_auction_api_service),
):
    logger.debug("New request to get similar archived sales prices", extra={"data": data.model_dump()})
    result = await _similar_history(api, data)

    prices: list[int] = []
    for lot in result.data:
        price = getattr(lot, "purchase_price", None)
        if isinstance(price, int) and price > 0:
            prices.append(price)

    if not prices:
        return SimilarArchivedSalesPricesOut()

    return SimilarArchivedSalesPricesOut(
        min_price=min(prices),
        avg_price=round(sum(prices) / len(prices), 2),
        max_price=max(prices),
        processed_lots=len(prices),
    )
