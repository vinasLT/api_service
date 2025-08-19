from typing import Union, Optional

from pydantic import BaseModel, field_validator, Field

from auction_api.types.search import SiteEnum
from auction_api.utils import AuctionApiUtils


class VinOrLotIn(BaseModel):
    site: Optional[SiteEnum] = Field(None, description="Auction site 1 or 2 or copart or iaai")
    vin_or_lot: str

    @field_validator('site', mode='before')
    @classmethod
    def validate_site(cls, v) -> Optional[int]:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return AuctionApiUtils.normalize_auction_to_num(v)

