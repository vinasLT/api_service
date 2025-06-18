from typing import Union, Optional

from pydantic import BaseModel, field_validator

from auction_api.utils import AuctionApiUtils


class VinOrLotIn(BaseModel):
    site: Optional[Union[int, str]]
    vin_or_lot: str

    @field_validator('site', mode='before')
    @classmethod
    def validate_site(cls, v) -> Optional[int]:
        """
        При пустом значении просто возвращаем None,
        иначе нормализуем через вспомогательную функцию.
        """
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        return AuctionApiUtils.normalize_auction_to_num(v)

