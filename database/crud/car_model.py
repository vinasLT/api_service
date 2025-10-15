from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models import Make
from database.models.car_model import Model
from database.schemas.filters import FilterCreate, FilterUpdate


class ModelService(BaseService[Model, FilterCreate, FilterUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Model, session)

    async def get_by_make(self, make: Make) -> Sequence[Model]:
        result = await self.session.execute(
            select(Model).where(Model.make_id == make.id).order_by(Model.name.asc())
        )
        return result.scalars().all()
