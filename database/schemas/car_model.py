from pydantic import BaseModel, ConfigDict
from typing import Optional


class ModelCreate(BaseModel):
    name: str
    slug: str


class ModelUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None

class ModelRead(ModelCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
