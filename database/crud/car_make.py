from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models.car_make import Make
from database.schemas.car_make import MakeCreate, MakeUpdate


class MakeService(BaseService[Make, MakeCreate, MakeUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Make, session)

