from datetime import datetime
from typing import Type, Literal, Optional, List, Union

from pydantic import BaseModel, PositiveInt, HttpUrl, field_validator, Field, model_validator

from auction_api.utils import AuctionApiUtils


class EndpointSchema(BaseModel):
    validation_schema: Type[BaseModel]
    method: str = Literal['GET', 'POST']
    endpoint: str
    out_schema_default: Type[BaseModel]
    out_schema_history: Optional[Type[BaseModel]] = None
    is_list: bool = False


class BasicLot(BaseModel):
    lot_id: int
    site: int
    base_site: str
    salvage_id: Optional[int]
    odometer: Optional[int]
    price_new: Optional[int]
    price_future: Optional[int]
    reserve_price: Optional[int]
    current_bid: Optional[int] = Field(0)
    auction_date: Optional[datetime] = Field(None)
    cost_priced: Optional[int]
    cost_repair: Optional[int]
    year: Optional[int]
    cylinders: Optional[int]
    state: Optional[str]
    vehicle_type: Optional[str]
    auction_type: Optional[str]
    make: Optional[str]
    model: Optional[str]
    series: Optional[str]
    damage_pr: Optional[str]
    damage_sec: Optional[str]
    keys: Optional[str]
    odobrand: Optional[str]
    fuel: Optional[str]
    drive: Optional[str]
    transmission: Optional[str]
    color: Optional[str]
    status: Optional[str]
    title: Optional[str]
    vin: Optional[str]
    engine: Optional[str]
    engine_size: Optional[float]
    location: Optional[str]
    location_old: Optional[str]
    location_id: Optional[int]
    country: Optional[str]
    document: Optional[str]
    document_old: Optional[str]
    currency: Optional[str]
    seller: Optional[str]
    is_buynow: bool
    iaai_360: Optional[str]
    copart_exterior_360: List[str]
    copart_interior_360: Optional[str]
    video: Optional[str]
    link_img_hd: List[HttpUrl]
    link_img_small: List[HttpUrl]
    is_offsite: bool
    location_offsite: Optional[str]
    link: HttpUrl
    body_type: Optional[str] = Field(None)
    seller_type: Optional[str]
    vehicle_score: Optional[str]
    form_get_type: str = Field(default='history')


class SaleHistoryItem(BaseModel):
    lot_id: int
    site: int
    base_site: str
    vin: str
    sale_status: str
    sale_date: datetime
    purchase_price: Optional[int]
    is_buynow: bool
    buyer_state: Optional[str]
    buyer_country: Optional[str]
    vehicle_type: Optional[str]

    @model_validator(mode="before")
    @classmethod
    def validate_together(cls, data: dict):
        base_site = data.get("base_site")
        site = data.get("site")

        if not base_site:
            data["base_site"] = AuctionApiUtils.num_to_auction_name(site)

        return data



class BasicHistoryLot(BasicLot):
    sale_history: Optional[List[SaleHistoryItem]]
    sale_date: Optional[datetime]
    sale_status: Optional[str]
    purchase_price: Optional[int]


class LotByIDIn(BaseModel):
    lot_id: PositiveInt
    site: Optional[Union[int, str]]

    @field_validator('site')
    @classmethod
    def validate_site(cls, v)-> int:
        return AuctionApiUtils.normalize_auction_to_num(v)

class LotByVINIn(BaseModel):
    vin: str
    site: Optional[Union[int, str]]

class CurrentBidOut(BaseModel):
    pre_bid: PositiveInt
