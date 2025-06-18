import asyncio
from pydantic import HttpUrl

from auction_api import EndpointSchema
from auction_api.types import LotByIDIn, BasicLot, BasicHistoryLot, LotByVINIn, CurrentBidOut
from basic_api import BaseClient, BaseClientIn
from config import AUCTION_API_KEY
from exptions import BadRequestException


class AuctionApiClient(BaseClient):
    GET_LOT_BY_ID_FOR_ALL_TIME = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint='cars/lot-id/all/',
        out_schema_default=BasicLot,
        out_schema_history=BasicHistoryLot,
        is_list=True
    )

    GET_LOT_BY_VIN_FOR_ALL_TIME = EndpointSchema(
        validation_schema=LotByVINIn,
        method='GET',
        endpoint='cars/vin/all/',
        out_schema_default=BasicLot,
        out_schema_history=BasicHistoryLot,
        is_list=True
    )

    GET_LOT_BY_ID_FOR_CURRENT = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint='cars/{lot_id}/',
        out_schema_default=BasicLot,
        is_list=True
    )

    GET_CURRENT_BID_FOR_LOT = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint='cars/current-bid/',
        out_schema_default=CurrentBidOut
    )

    GET_LOT_HISTORY_BY_ID = EndpointSchema(
        validation_schema=LotByIDIn,
        method='GET',
        endpoint='sale-histories/lot-id/',
        out_schema_default=BasicHistoryLot,
    )
    HISTORY_VIN_ENDPOINT = 'sale-histories/vin/'
    GET_LOT_HISTORY_BY_VIN = EndpointSchema(
        validation_schema=LotByVINIn,
        method='GET',
        endpoint=HISTORY_VIN_ENDPOINT,
        out_schema_default=BasicHistoryLot,
    )


    def __init__(self):
        data = BaseClientIn(
            base_url=HttpUrl('https://api.apicar.store/api'),
            api_key=AUCTION_API_KEY,
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
            raise BadRequestException('Wrong form_get_type', 'wrong_form_get_type')

    def process_response(self, response_data: dict | list, schema: EndpointSchema):
        if not schema.out_schema_history is None:
            if schema.is_list:
                items = response_data if isinstance(response_data, list) else [response_data]
                return [
                    (schema.out_schema_history if self.is_item_history(item) else schema.out_schema_default).model_validate(
                        item)
                    for item in items
                ]

            out_schema = schema.out_schema_history if self.is_item_history(response_data) else schema.out_schema_default
        else:
            out_schema = schema.out_schema_default

        if schema.endpoint == self.HISTORY_VIN_ENDPOINT:
            response_data = response_data['data']

        return out_schema.model_validate(response_data)

if __name__ == '__main__':
    async def main():
        api = AuctionApiClient()
        response = await api.request_with_schema(api.GET_LOT_BY_ID_FOR_ALL_TIME, LotByIDIn(lot_id=47549705, site='copart'))
        print(response)

    asyncio.run(main())


