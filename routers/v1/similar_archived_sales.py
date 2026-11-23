from fastapi import APIRouter, Depends, Query

from auction_api.api import AuctionApiClient
from auction_api.types.search import BasicManyHistoryLot, HistorySearchParams
from core.logger import logger
from dependencies.auction_api_service import get_auction_api_service
from request_schemas.lot import GetAveragedPriceIn, StatisticsData, StatItem
from schemas.similar_archived_sales import SimilarArchivedSalesPricesOut
from schemas.similar_history_lots import SimilarHistoryLots
from services.provider_cache import TTL_HISTORY_CARS_SIMILAR, cached_provider_call

similar_sales_router = APIRouter()
STATISTIC_PERIOD_MONTHS = 6


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


def _item_average(item: StatItem) -> float | None:
    if not item.count or item.total is None:
        return None
    return float(item.total)


def prices_from_statistics(stats: StatisticsData) -> SimilarArchivedSalesPricesOut:
    items = [item for item in stats.root.values() if isinstance(item, StatItem)]
    if not items:
        return SimilarArchivedSalesPricesOut()

    mins = [item.min for item in items if isinstance(item.min, int)]
    maxs = [item.max for item in items if isinstance(item.max, int)]
    weighted_total = 0.0
    weighted_count = 0
    for item in items:
        average = _item_average(item)
        count = item.count or 0
        if average is None or count <= 0:
            continue
        weighted_total += average * count
        weighted_count += count

    if weighted_count == 0 and not mins and not maxs:
        return SimilarArchivedSalesPricesOut()

    return SimilarArchivedSalesPricesOut(
        min_price=min(mins) if mins else None,
        avg_price=round(weighted_total / weighted_count, 2) if weighted_count else None,
        max_price=max(maxs) if maxs else None,
        processed_lots=weighted_count,
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
    if not data.model:
        return SimilarArchivedSalesPricesOut()

    year_from = data.year - 5 if data.year is not None else None
    year_to = data.year + 5 if data.year is not None else None
    request = GetAveragedPriceIn(
        make=data.make,
        model=data.model,
        year_from=year_from,
        year_to=year_to,
        period=STATISTIC_PERIOD_MONTHS,
    )
    stats = await cached_provider_call(
        api,
        AuctionApiClient.GET_AVERAGES_FOR_LOT,
        request,
        ttl=TTL_HISTORY_CARS_SIMILAR,
    )
    return prices_from_statistics(stats)
