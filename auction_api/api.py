from datetime import datetime, UTC
from enum import Enum
from typing import Optional

from pydantic import HttpUrl, BaseModel, ValidationError
from rfc9457 import BadRequestProblem, NotFoundProblem

from auction_api.types.db_lot import DBUpdateLot, DBDeleteLot
from auction_api.types.lot import BasicLot, BasicHistoryLot
from auction_api.types.search import (
    BasicManyCurrentLots,
    BasicManyHistoryLot,
    HistorySearchParams,
    CurrentSearchParams,
    DBManyLots,
    DBManyDeletedLots,
)
from basic_api import BaseClient, BaseClientIn
from config import settings
from core.logger import logger
from request_schemas.db_save_schemas import DBCurrentUpdateIn, DBCurrentDeleteIn, DBAllLotsIn
from request_schemas.lot import LotByIDIn, LotByVINIn, CurrentBidOut, GetAveragedPriceIn, StatisticsData


class Endpoint(str, Enum):
    # current
    LOT_BY_ID_CURRENT = 'cars/{lot_id}'
    LOT_BY_VIN_CURRENT = 'cars/vin'
    LOTS_CURRENT = 'cars'

    # all time
    LOT_BY_VIN_FOR_ALL_TIME = 'cars/vin/all'
    LOT_BY_ID_WEB = 'cars/lot-id/web'

    # for lot
    CURRENT_BID_BY_ID = 'cars/current-bid'

    # history
    HISTORY_LOTS = 'history-cars'
    HISTORY_BY_ID = 'sale-histories/lot-id'
    HISTORY_BY_VIN = 'sale-histories/vin'

    #average price
    AVERAGE_PRICE = 'history-cars/statistic'

    # db creation
    DB_UPDATE_CURRENT = "db/cars/update"
    DB_DELETE_CURRENT = "db/cars/deleted"
    DB_GET_ALL = "db/cars/all"

class EndpointSchema(BaseModel):
    validation_schema: type[BaseModel]
    endpoint: Endpoint
    out_schema_default: type[BaseModel]
    out_schema_history: Optional[type[BaseModel]] = None
    is_pagination: Optional[bool] = False
    pagination_schema: Optional[type[BaseModel]] = None






_SALE_COUNT_KEYS = ("sale_count", "sales_count", "sale_histories_count", "count")
_missing_sale_count_logged = False


def _integer_sale_count(item: dict) -> int | None:
    for key in _SALE_COUNT_KEYS:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def _with_sale_count(item: dict, fallback: int | None) -> dict:
    global _missing_sale_count_logged
    count = _integer_sale_count(item)
    if count is None:
        count = fallback
    if count is None:
        if not _missing_sale_count_logged:
            _missing_sale_count_logged = True
            logger.info(
                "Web lot response has no sale count",
                extra={"data": {"keys": sorted(str(key) for key in item)}},
            )
        return item
    if item.get("sale_count") == count:
        return item
    copied = dict(item)
    copied["sale_count"] = count
    return copied


def prepare_web_response(payload):
    """Copy a documented-or-aliased sales count onto sale_count before validation."""
    if isinstance(payload, dict):
        inner = payload.get("data")
        if "lot_id" not in payload and isinstance(inner, dict):
            return _with_sale_count(inner, _integer_sale_count(payload))
        if "lot_id" not in payload and isinstance(inner, list):
            fallback = _integer_sale_count(payload)
            return [
                _with_sale_count(item, fallback) if isinstance(item, dict) else item
                for item in inner
            ]
        return _with_sale_count(payload, None)
    if isinstance(payload, list):
        return [
            _with_sale_count(item, None) if isinstance(item, dict) else item
            for item in payload
        ]
    return payload


class AuctionApiClient(BaseClient):
    GET_LOT_BY_ID_FOR_WEB = EndpointSchema(
        validation_schema=LotByIDIn,
        endpoint=Endpoint.LOT_BY_ID_WEB,
        out_schema_default=BasicLot,
        out_schema_history=BasicHistoryLot,
        is_pagination=False,
    )

    GET_LOT_BY_VIN_FOR_ALL_TIME = EndpointSchema(
        validation_schema=LotByVINIn,
        endpoint=Endpoint.LOT_BY_VIN_FOR_ALL_TIME,
        out_schema_default=BasicLot,
        out_schema_history=BasicHistoryLot,
        is_pagination=False,
    )

    GET_LOT_BY_VIN_FOR_CURRENT = EndpointSchema(
        validation_schema=LotByVINIn,
        endpoint=Endpoint.LOT_BY_VIN_CURRENT,
        out_schema_default=BasicLot,
        is_pagination=False,
    )

    GET_LOT_BY_ID_FOR_CURRENT = EndpointSchema(
        validation_schema=LotByIDIn,
        endpoint=Endpoint.LOT_BY_ID_CURRENT,
        out_schema_default=BasicLot,
        is_pagination=False,
    )

    GET_CURRENT_BID_FOR_LOT = EndpointSchema(
        validation_schema=LotByIDIn,
        endpoint=Endpoint.CURRENT_BID_BY_ID,
        out_schema_default=CurrentBidOut,
        is_pagination=False,
    )
    GET_LOT_HISTORY_BY_ID = EndpointSchema(
        validation_schema=LotByIDIn,
        endpoint=Endpoint.HISTORY_BY_ID,
        out_schema_default=BasicHistoryLot,
        is_pagination=False,
    )

    GET_LOT_HISTORY_BY_VIN = EndpointSchema(
        validation_schema=LotByVINIn,
        endpoint=Endpoint.HISTORY_BY_VIN,
        out_schema_default=BasicHistoryLot,
    )

    GET_CURRENT_LOTS = EndpointSchema(
        validation_schema=CurrentSearchParams,
        endpoint=Endpoint.LOTS_CURRENT,
        out_schema_default=BasicLot,
        is_pagination=True,
        pagination_schema=BasicManyCurrentLots
    )

    GET_HISTORY_LOTS = EndpointSchema(
        validation_schema=HistorySearchParams,
        endpoint=Endpoint.HISTORY_LOTS,
        out_schema_default=BasicHistoryLot,
        is_pagination=True,
        pagination_schema=BasicManyHistoryLot,
    )

    GET_AVERAGES_FOR_LOT = EndpointSchema(
        validation_schema=GetAveragedPriceIn,
        endpoint=Endpoint.AVERAGE_PRICE,
        out_schema_default=StatisticsData,
        is_pagination=False,
    )

    GET_DB_UPDATED_LOTS = EndpointSchema(
        validation_schema=DBCurrentUpdateIn,
        endpoint=Endpoint.DB_UPDATE_CURRENT,
        out_schema_default=DBUpdateLot,
        is_pagination=True,
        pagination_schema=DBManyLots,
    )

    GET_DB_DELETED_LOTS = EndpointSchema(
        validation_schema=DBCurrentDeleteIn,
        endpoint=Endpoint.DB_DELETE_CURRENT,
        out_schema_default=DBDeleteLot,
        is_pagination=True,
        pagination_schema=DBManyDeletedLots,
    )

    GET_DB_ALL_LOTS = EndpointSchema(
        validation_schema=DBAllLotsIn,
        endpoint=Endpoint.DB_GET_ALL,
        out_schema_default=DBUpdateLot,
        is_pagination=True,
        pagination_schema=DBManyLots,
    )



    def __init__(self):
        data = BaseClientIn(
            base_url=HttpUrl('https://api.apicar.store/api'),
            api_key=settings.AUCTION_API_KEY,
            header_name="api-key"
        )
        super().__init__(data)

    @staticmethod
    def model_for_item(schema: EndpointSchema, item: object):
        if (
            isinstance(item, dict)
            and schema.out_schema_history is not None
            and AuctionApiClient.is_item_history(item)
        ):
            return schema.out_schema_history
        return schema.out_schema_default

    @staticmethod
    def is_item_history(item: dict) -> bool:
        if item.get('form_get_type') == 'active':
            return False
        elif item.get('form_get_type') == 'history':
            return True
        else:
            auction_date = item.get('auction_date')
            sale_date = item.get('sale_date')
            if sale_date:
                return True

            if auction_date:
                clean_string = auction_date.replace('Z', '+00:00')
                dt_object = datetime.fromisoformat(clean_string)

                if dt_object.tzinfo is None:
                    dt_object = dt_object.replace(tzinfo=UTC)

                now = datetime.now(UTC)
                return dt_object <= now
        return True

    def process_response(self, response_data: dict | list, schema: EndpointSchema):
        if isinstance(response_data, dict) and isinstance(response_data.get('data'), list):
            item_count = len(response_data['data'])
        elif isinstance(response_data, list):
            item_count = len(response_data)
        else:
            item_count = None
        logger.debug('Processing API response', extra={'endpoint': schema.endpoint.value, 'item_count': item_count})
        if response_data is None:
            logger.error('No data from API, "response_data" is None"')
            raise BadRequestProblem(detail='Not data from API')
        if schema.is_pagination and schema.pagination_schema:
            if isinstance(response_data, dict) and 'data' in response_data:
                try:
                    processed_items = []
                    for item in response_data.get('data', []):
                        processed_items.append(
                            self.model_for_item(schema, item).model_validate(item)
                        )

                    paginated_response = {
                        'size': response_data.get('size'),
                        'page': response_data.get('page'),
                        'pages': response_data.get('pages', 1000),
                        'count': response_data.get('count', 1000000),
                        'data': processed_items
                    }
                    return schema.pagination_schema.model_validate(paginated_response)
                except ValidationError as e:
                    logger.error(f'Validation error in pagination schema: {str(e)[:1000]}',
                                 extra={'endpoint': schema.endpoint.value, 'error': str(e)[:1000]})
                    raise BadRequestProblem(detail='Validation error in data from API')

        if schema.endpoint is Endpoint.LOT_BY_ID_WEB:
            response_data = prepare_web_response(response_data)
            if isinstance(response_data, list) and len(response_data) == 0:
                raise NotFoundProblem("Lot not found")
        if schema.endpoint in [Endpoint.HISTORY_BY_VIN, Endpoint.HISTORY_BY_ID]:
            response_data = response_data.get('data', response_data)
        try:
            if schema.out_schema_history is not None and isinstance(response_data, list):
                processed_items = [
                    self.model_for_item(schema, item).model_validate(item)
                    for item in response_data
                ]
                return processed_items[0] if len(processed_items) == 1 else processed_items

            if schema.out_schema_history is not None and isinstance(response_data, dict):
                return self.model_for_item(schema, response_data).model_validate(response_data)

            return schema.out_schema_default.model_validate(response_data)
        except ValidationError as e:
            logger.error(f'Validation error in schema: {str(e)[:1000]}',
                         extra={'endpoint': schema.endpoint.value,
                                'schema': schema.out_schema_default.__name__,
                                'error': str(e)[:1000]})
            raise BadRequestProblem(detail='Validation error in data from API')


