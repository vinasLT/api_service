from typing import Literal, Type

from pydantic import BaseModel, HttpUrl, PositiveInt


class BaseClientIn(BaseModel):
    api_key: str
    header_name: str = 'api-key'
    base_url: HttpUrl




