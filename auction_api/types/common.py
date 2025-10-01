from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator

class SiteEnum(str, Enum):
    """Auction site enumeration"""
    COPART = 'copart'
    IAAI = 'iaai'
    COPART_NUM = '1'
    IAAI_NUM = '2'
    ALL = 'all'
    ALL_NUM = '3'


class SiteIn(BaseModel):
    site: Optional[SiteEnum] = Field(..., description="Auction site 1 or 2 or copart or iaai")

    @field_validator('site', mode='before')
    @classmethod
    def validate_site(cls, v):
        from auction_api.utils import AuctionApiUtils
        if v is None:
            return v
        return SiteEnum(str(AuctionApiUtils.normalize_auction_to_num(v)))