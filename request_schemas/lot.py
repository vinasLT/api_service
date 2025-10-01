

from pydantic import BaseModel, Field

from auction_api.types.common import SiteIn, DefinedSiteEnum


class LotByIDIn(SiteIn):
    site: DefinedSiteEnum | None = Field(None, description="Auction of vehicle")
    lot_id: int = Field(..., description="Lot id")


class LotByVINIn(SiteIn):
    vin: str = Field(..., description="VIN of vehicle")


class CurrentBidOut(BaseModel):
    pre_bid: int

