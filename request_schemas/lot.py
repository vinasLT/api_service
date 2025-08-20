

from pydantic import BaseModel, Field

from auction_api.types.search import SiteIn


class LotByIDIn(SiteIn):
    lot_id: int = Field(..., description="Lot id")


class LotByVINIn(SiteIn):
    vin: str = Field(..., description="VIN of vehicle")


class CurrentBidOut(BaseModel):
    pre_bid: int

