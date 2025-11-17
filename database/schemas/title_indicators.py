from typing import Optional

from pydantic import BaseModel, ConfigDict

from auction_api.types.common import SiteEnum


class TitleIndicatorCreate(BaseModel):
    site: SiteEnum
    title_name: str
    status: str


class TitleIndicatorUpdate(BaseModel):
    site: Optional[SiteEnum] = None
    title_name: Optional[str] = None
    status: Optional[str] = None


class TitleIndicatorRead(TitleIndicatorCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
