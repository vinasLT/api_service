from typing import Union, TYPE_CHECKING

from pydantic_core import PydanticCustomError
from rfc9457 import BadRequestProblem, NotFoundProblem

from auction_api.wmi_country import decode_wmi_country
from core.logger import logger
from request_schemas.lot import LotByIDIn, LotByVINIn

if TYPE_CHECKING:
    from auction_api.api import AuctionApiClient
    from auction_api.types.search import SiteEnum


class AuctionApiUtils:
    AUCTION_NUM = {
        'copart': 1,
        'iaai': 2,
        'all': 3
    }

    @classmethod
    def num_to_auction_name(cls, num: int) -> str:
        for key, value in cls.AUCTION_NUM.items():
            if num == value:
                return key
        raise PydanticCustomError('wrong_auction_number', 'Wrong auction number')

    @classmethod
    def auction_name_to_num(cls, auction_name: str) -> int:
        num = cls.AUCTION_NUM.get(auction_name.lower())
        if num is None:
            raise PydanticCustomError( 'wrong_auction_name', 'Wrong auction name')
        return num

    @classmethod
    def normalize_auction_to_num(cls, auction: Union[str, int])-> int | None:
        if auction is None:
            return auction
        if isinstance(auction, str) and not auction.isdigit():
            return cls.auction_name_to_num(auction)
        elif isinstance(auction, int):
            return auction
        elif auction.isdigit():
            return int(auction)
        raise PydanticCustomError('wrong_auction', 'Wrong auction')

    @classmethod
    def get_manufacturer_country(cls, vin: str | None) -> str | None:
        return decode_wmi_country(vin)


async def get_lot_vin_or_lot_id(api: "AuctionApiClient", site: "SiteEnum", vin_or_lot_id: str):
    """Lot ids use the catalog endpoint. A VIN uses the current endpoint, then all-time on 404."""
    from services.provider_cache import (
        TTL_CURRENT_LOT,
        cached_provider_call,
        catalog_lot_ttl,
        sale_history_ttl,
    )

    vin_or_lot = vin_or_lot_id.replace(" ", "").upper()
    if len(vin_or_lot) > 64:
        raise BadRequestProblem(detail="Identifier is too long")
    if vin_or_lot.isdigit():
        logger.debug(
            f"Request routed to get by lot_id - {vin_or_lot}",
            extra={"site": site, "vin_or_lot_id": vin_or_lot},
        )
        return await cached_provider_call(
            api,
            api.GET_LOT_BY_ID_FOR_WEB,
            LotByIDIn(site=site, lot_id=int(vin_or_lot)),
            ttl=catalog_lot_ttl,
        )

    logger.debug(
        f"Request routed to get by vin - {vin_or_lot}",
        extra={"site": site, "vin_or_lot_id": vin_or_lot},
    )
    # GET /cars/vin accepts vin only. site stays on the all-time fallback.
    try:
        return await cached_provider_call(
            api,
            api.GET_LOT_BY_VIN_FOR_CURRENT,
            LotByVINIn(vin=vin_or_lot, site=None),
            ttl=TTL_CURRENT_LOT,
        )
    except NotFoundProblem:
        return await cached_provider_call(
            api,
            api.GET_LOT_BY_VIN_FOR_ALL_TIME,
            LotByVINIn(vin=vin_or_lot, site=site),
            ttl=sale_history_ttl,
        )

