from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


class BaseService:
    def __init__(self, model: type, session: AsyncSession | None = None):
        self.model = model
        self.session = session

    async def get(self, obj_id: int):
        return await self.session.get(self.model, obj_id)

    async def get_all_sorted(self, sort_by: str, sort_order: str = "asc") -> Sequence:
        sort_order = sort_order.lower()
        if sort_order not in ("asc", "desc"):
            raise ValueError("sort_order must be either 'asc' or 'desc'")
        sort_field = getattr(self.model, sort_by, None)
        if sort_field is None:
            raise AttributeError(f"Model {self.model.__name__} has no field '{sort_by}'")
        result = await self.session.execute(
            select(self.model).order_by(sort_field.desc() if sort_order == "desc" else sort_field.asc())
        )
        return result.scalars().all()

    async def get_by_field(self, field_name: str, value):
        field = getattr(self.model, field_name, None)
        if field is None:
            raise AttributeError(f"Model {self.model.__name__} has no field '{field_name}'")
        result = await self.session.execute(
            select(self.model).where(field == value).limit(1)
        )
        return result.scalar_one_or_none()
