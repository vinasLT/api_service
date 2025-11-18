from fastapi import APIRouter, Query, Depends

from auction_api.api import AuctionApiClient
from auction_api.types.search import HistorySearchParams, BasicManyCurrentLots
from core.logger import logger
from dependencies.auction_api_service import get_auction_api_service
from schemas.similar_history_lots import SimilarHistoryLots

similar_sales_router = APIRouter()


@similar_sales_router.get('', response_model=BasicManyCurrentLots)
async def get_similar_sales(
        data: SimilarHistoryLots = Query(...),
        api: AuctionApiClient = Depends(get_auction_api_service)
):
    data = HistorySearchParams(make=data.make, model=data.model, year_from=data.year - 5, year_to=data.year + 5,
                               vehicle_type=data.vehicle_type, site=data.site)
    logger.debug('New request to get many history lots', extra={'data': data.model_dump()})
    return await api.request_with_schema(AuctionApiClient.GET_HISTORY_LOTS, data)