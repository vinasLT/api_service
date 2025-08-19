from typing import Optional, Union

from pydantic import BaseModel, field_validator, Field

from auction_api.types.search import SiteEnum
from auction_api.utils import AuctionApiUtils

class SiteIn(BaseModel):
    site: Optional[SiteEnum] = Field(..., description="Auction site 1 or 2 or copart or iaai")

    @field_validator('site')
    @classmethod
    def validate_site(cls, v) -> int:
        return AuctionApiUtils.normalize_auction_to_num(v)


class LotByIDIn(SiteIn):
    lot_id: int = Field(..., description="Lot id ")


class LotByVINIn(SiteIn):
    vin: str = Field(..., description="VIN of vehicle")


class CurrentBidOut(BaseModel):
    pre_bid: int

