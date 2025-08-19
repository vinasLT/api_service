from pydantic import BaseModel, ConfigDict
from typing import Optional


class MakeCreate(BaseModel):
    name: str
    slug: str


class MakeUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None

class MakeRead(MakeCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)
