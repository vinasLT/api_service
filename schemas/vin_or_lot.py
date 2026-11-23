from pydantic import Field

from auction_api.types.common import SiteEnum
from request_schemas.lot import SiteIn


class VinOrLotIn(SiteIn):
    site: SiteEnum | None = Field(None, description="Auction of vehicle")
    vin_or_lot: str


