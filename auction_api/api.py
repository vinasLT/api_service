import asyncio
from datetime import datetime, UTC
from enum import Enum
from typing import Optional, Literal

from pydantic import HttpUrl, BaseModel

from auction_api.types.lot import BasicLot, BasicHistoryLot
from auction_api.types.search import BasicManyCurrentLots, HistorySearchParams, CurrentSearchParams
from basic_api import BaseClient, BaseClientIn
from config import settings
from exptions import BadRequestException
from request_schemas.lot import LotByIDIn, LotByVINIn, CurrentBidOut


class Endpoint(str, Enum):
    # current
    LOT_BY_ID_CURRENT = 'cars/{lot_id}/'
    LOTS_CURRENT = 'cars/'

    # all time
    LOT_BY_VIN_FOR_ALL_TIME = 'cars/vin/all/'
    LOT_BY_ID_FOR_ALL_TIME = 'cars/lot-id/all/'

    # for lot
    CURRENT_BID_BY_ID = 'cars/current-bid/'

    # history
    HISTORY_LOTS = 'history-cars/'
    HISTORY_BY_ID = 'sale-histories/lot-id/'
    HISTORY_BY_VIN = 'sale-histories/vin/'

class EndpointSchema(BaseModel):
    validation_schema: type[BaseModel]
    method: str = Literal['GET', 'POST']
    endpoint: Endpoint
    out_schema_default: type[BaseModel]
    out_schema_history: Optional[type[BaseModel]] = None
    is_pagination: Optional[bool] = False
    pagination_schema: Optional[type[BaseModel]] = None






class AuctionApiClient(BaseClient):
    GET_LOT_BY_ID_FOR_ALL_TIME = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint=Endpoint.LOT_BY_ID_FOR_ALL_TIME,
        out_schema_default=BasicLot,
        out_schema_history=BasicHistoryLot,
        is_pagination=False,
    )

    GET_LOT_BY_VIN_FOR_ALL_TIME = EndpointSchema(
        validation_schema=LotByVINIn,
        method='GET',
        endpoint=Endpoint.LOT_BY_VIN_FOR_ALL_TIME,
        out_schema_default=BasicLot,
        out_schema_history=BasicHistoryLot,
        is_pagination=False,
    )

    GET_LOT_BY_ID_FOR_CURRENT = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint=Endpoint.LOT_BY_ID_CURRENT,
        out_schema_default=BasicLot,
        is_pagination=False,
    )

    GET_CURRENT_BID_FOR_LOT = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint=Endpoint.CURRENT_BID_BY_ID,
        out_schema_default=CurrentBidOut,
        is_pagination=False,
    )
    GET_LOT_HISTORY_BY_ID = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint=Endpoint.HISTORY_BY_ID,
        out_schema_default=BasicHistoryLot,
        is_pagination=False,
    )

    GET_LOT_HISTORY_BY_VIN = EndpointSchema(
        validation_schema=LotByVINIn,
        method='GET',
        endpoint=Endpoint.HISTORY_BY_VIN,
        out_schema_default=BasicHistoryLot,
    )


    GET_CURRENT_LOTS = EndpointSchema(
        validation_schema=CurrentSearchParams,
        method='GET',
        endpoint=Endpoint.LOTS_CURRENT,
        out_schema_default=BasicLot,
        is_pagination=True,
        pagination_schema=BasicManyCurrentLots
    )

    GET_HISTORY_LOTS = EndpointSchema(
        validation_schema=HistorySearchParams,
        method='GET',
        endpoint=Endpoint.HISTORY_LOTS,
        out_schema_default=BasicHistoryLot,
        is_pagination=True,
        pagination_schema=BasicManyCurrentLots
    )



    def __init__(self):
        data = BaseClientIn(
            base_url=HttpUrl('https://api.apicar.store/api'),
            api_key=settings.AUCTION_API_KEY,
            header_name="api-key"
        )
        super().__init__(data)

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
            else:
                return True
            # TODO: replace exception
            raise BadRequestException('Wrong form_get_type', 'wrong_form_get_type')

    def process_response(self, response_data: dict | list, schema: EndpointSchema):
        if schema.is_pagination and schema.pagination_schema:
            if schema.is_pagination and schema.pagination_schema:
                if isinstance(response_data, dict) and 'data' in response_data:
                    processed_items = []
                    for item in response_data['data']:
                        item_schema = (
                            schema.out_schema_history
                            if schema.out_schema_history and self.is_item_history(item)
                            else schema.out_schema_default
                        )
                        processed_items.append(item_schema.model_validate(item))

                    paginated_response = {
                        'size': response_data.get('size'),
                        'page': response_data.get('page'),
                        'pages': response_data.get('pages', 1000),
                        'count': response_data.get('count', 1000000),
                        'data': processed_items
                    }
                    return schema.pagination_schema.model_validate(paginated_response)

        if schema.endpoint in [Endpoint.HISTORY_BY_VIN, Endpoint.HISTORY_BY_ID]:
            response_data = response_data.get('data', response_data)

        if schema.out_schema_history is not None:
            if isinstance(response_data, list):
                processed_items = [
                    (schema.out_schema_history if self.is_item_history(item)
                     else schema.out_schema_default).model_validate(item)
                    for item in response_data
                ]
                return processed_items[0] if len(processed_items) == 1 else processed_items

            if isinstance(response_data, dict) and 'lot_id' in response_data:
                return schema.out_schema_history.model_validate(response_data)

            if response_data and self.is_item_history(response_data):
                return schema.out_schema_history.model_validate(response_data)

        return schema.out_schema_default.model_validate(response_data)

if __name__ == '__main__':
    async def main():
        api = AuctionApiClient()
        response = await api.request_with_schema(api.GET_HISTORY_LOTS, HistorySearchParams(seller_type='dealer'))
        print(response)
        print(type(response))
        print(len(response.data))
        print(response.data[-1])




    asyncio.run(main())


