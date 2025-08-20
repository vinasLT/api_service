from typing import Optional

from pydantic import BaseModel, field_validator, Field

from auction_api.types.search import SiteEnum
from auction_api.utils import AuctionApiUtils
from request_schemas.lot import SiteIn


class VinOrLotIn(SiteIn):
    vin_or_lot: str

    @classmethod
    def validate_site(cls, v):
        return v


