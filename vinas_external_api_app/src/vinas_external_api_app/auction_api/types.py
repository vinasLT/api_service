from datetime import datetime
from typing import Type, Literal, Optional, List, Union

from pydantic import BaseModel, PositiveInt, HttpUrl, field_validator, Field

from vinas_external_api_app.src.vinas_external_api_app.auction_api.utils import AuctionApiUtils


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
    salvage_id: Optional[str]
    odometer: Optional[int]
    price_new: Optional[int]
    price_future: Optional[int]
    reserve_price: Optional[int]
    current_bid: Optional[int]
    auction_date: Optional[datetime]
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
    body_type: Optional[str]
    seller_type: Optional[str]
    vehicle_score: Optional[str]
    form_get_type: str = Field(default='active')


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


class BasicHistoryLot(BasicLot):
    sale_history: Optional[List[SaleHistoryItem]]
    sale_date: Optional[datetime]
    sale_status: Optional[str]
    purchase_price: Optional[int]


class LotByIDIn(BaseModel):
    lot_id: PositiveInt
    site: Union[int, str]

    @field_validator('site')
    @classmethod
    def validate_site(cls, v)-> int:
        return AuctionApiUtils.normalize_auction_to_num(v)

class LotByVINIn(BaseModel):
    vin: str
    site: Union[int, str]

class CurrentBidOut(BaseModel):
    pre_bid: PositiveInt
