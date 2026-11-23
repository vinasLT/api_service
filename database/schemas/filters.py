from pydantic import BaseModel, ConfigDict


class FilterRead(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)
