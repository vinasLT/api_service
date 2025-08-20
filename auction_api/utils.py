from typing import Union

from pydantic_core import PydanticCustomError


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
        raise PydanticCustomError('wrong_auction_number', 'Wrong auction number')

    @classmethod
    def auction_name_to_num(cls, auction_name: str) -> int:
        num = cls.AUCTION_NUM.get(auction_name.lower())
        if num is None:
            raise PydanticCustomError( 'wrong_auction_name', 'Wrong auction name')
        return num

    @classmethod
    def normalize_auction_to_num(cls, auction: Union[str, int])-> int | None:
        if auction is None:
            return auction
        if isinstance(auction, str) and not auction.isdigit():
            return cls.auction_name_to_num(auction)
        elif isinstance(auction, int):
            return auction
        elif auction.isdigit():
            return int(auction)
        raise PydanticCustomError('wrong_auction', 'Wrong auction')


