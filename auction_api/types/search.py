from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

from auction_api.types.lot import BasicLot, BasicHistoryLot
from auction_api.utils import AuctionApiUtils


class BasicPaginationInfo(BaseModel):
    size: int
    page: int
    pages: int
    count: int

class BasicManyCurrentLots(BasicPaginationInfo):
    data: list[BasicLot]

class BasicManyHistoryLot(BasicPaginationInfo):
    data: list[BasicHistoryLot]


class SiteEnum(str, Enum):
    """Auction site enumeration"""
    COPART = 'copart'
    IAAI = 'iaai'
    COPART_NUM = '1'
    IAAI_NUM = '2'


class SortEnum(str, Enum):
    """Sort field enumeration"""
    AUCTION_DATE = "auction_date"
    CREATED_AT = "created_at"


class DirectionEnum(str, Enum):
    """Sort direction enumeration"""
    ASC = "ASC"
    DESC = "DESC"

class VehicleTypeEnum(str, Enum):
    AUTOMOBILE = 'automobile'
    TRUCK = 'truck'
    TRAILERS = 'trailers'
    MOTORCYCLE = 'motorcycle'
    BOAT = 'boat'
    ATV = 'atv'
    WATERCRAFT = 'watercraft'
    BUS = 'bus'
    INDUSTRIAL_EQUIPMENT = 'industrial_equipment'
    JET_SKY = 'jet_sky'
    OTHER = 'other'


class SellerTypeEnum(str, Enum):
    INSURANCE = 'insurance'
    DEALER = 'dealer'


class SiteIn(BaseModel):
    site: Optional[SiteEnum] = Field(..., description="Auction site 1 or 2 or copart or iaai")

    @field_validator('site', mode='after')
    @classmethod
    def validate_site(cls, v):
        if v is None:
            return v
        return SiteEnum(str(AuctionApiUtils.normalize_auction_to_num(v)))



class CommonSearchParams(SiteIn):
    make: Optional[str] = Field(None, description="Vehicle make")
    model: Optional[str] = Field(None, description="Vehicle model")
    vehicle_type: Optional[str] = Field(None, description="Vehicle type")
    year_from: Optional[int] = Field(None, ge=1900, le=2030, description="Year from")
    year_to: Optional[int] = Field(None, ge=1900, le=2030, description="Year to")
    auction_date_from: Optional[datetime] = Field(None, description="Auction date from, '2025-08-18'",
                                                  examples=['2025-08-18'])
    auction_date_to: Optional[datetime] = Field(None, description="Auction date to, '2025-08-18'",
                                                examples=['2025-08-18'])

    transmission: Optional[list[str]] = Field(None, description="Transmission types")
    status: Optional[list[str]] = Field(None, description="Vehicle statuses")

    drive: Optional[list[str]] = Field(None, description="Drive types")
    damage_pr: Optional[list[str]] = Field(None, description="Primary damage types")

    document: Optional[list[str]] = Field(None, description="Document types")
    odometer_min: Optional[int] = Field(None, ge=0, description="Minimum odometer")
    odometer_max: Optional[int] = Field(None, ge=0, description="Maximum odometer")
    seller_type: Optional[SellerTypeEnum] = Field(None, description="Seller type")
    sort: Optional[SortEnum] = Field(None, description="Sort field")
    direction: Optional[DirectionEnum] = Field(None, description="Sort direction")

    page: Optional[int] = Field(1, ge=1, description="Page number")
    size: Optional[int] = Field(10, ge=1, le=30, description="Lots per page (max 30)")

    model_config = ConfigDict(use_enum_values=True)


class CurrentSearchParams(CommonSearchParams):
    buy_now: Optional[bool] = Field(None, description="Get only Buy Now lots")
    fuel: Optional[list[str]] = Field(None, description="Fuel types")

class HistorySearchParams(CommonSearchParams):
    pass






