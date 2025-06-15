from typing import Union

from pydantic import BaseModel, field_validator

from auction_api.utils import AuctionApiUtils


class VinOrLotIn(BaseModel):
    site: Union[int, str]
    vin_or_lot: str

    @field_validator('site')
    @classmethod
    def validate_site(cls, v) -> int:
        return AuctionApiUtils.normalize_auction_to_num(v)

