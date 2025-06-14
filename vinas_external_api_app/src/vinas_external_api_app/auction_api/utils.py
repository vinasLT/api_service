import re
from typing import Union

from pydantic import BaseModel

from vinas_external_api_app.src.vinas_external_api_app.exptions import BadRequestException



class AuctionApiUtils:
    AUCTION_NUM = {
        'copart': 1,
        'iaai': 2
    }

    @classmethod
    def num_to_auction_name(cls, num: int) -> str:
        for key, value in cls.AUCTION_NUM.items():
            if num == value:
                return key
        raise BadRequestException('Wrong auction number', 'wrong_auction_number')

    @classmethod
    def auction_name_to_num(cls, auction_name: str) -> int:
        num = cls.AUCTION_NUM.get(auction_name.lower())
        if num is None:
            raise BadRequestException('Wrong auction name', 'wrong_auction_name')
        return num

    @classmethod
    def normalize_auction_to_num(cls, auction: Union[str, int])-> int:
        if isinstance(auction, str) and not auction.isdigit():
            return cls.auction_name_to_num(auction)
        elif isinstance(auction, int):
            return auction
        elif auction.isdigit():
            return int(auction)
        raise BadRequestException('Wrong auction', 'wrong_auction')

    @staticmethod
    def set_value_in_path(endpoint: str, data: BaseModel) -> str:
        placeholders = re.findall(r'{(\w+)}', endpoint)
        if not placeholders:
            return endpoint

        data_dict = data.model_dump()

        for key in placeholders:
            if key in data_dict:
                endpoint = endpoint.replace(f'{{{key}}}', str(data_dict[key]))
            else:
                raise ValueError(f"Field '{key}' not found in model")

        return endpoint


