from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models.car_model import Model
from database.schemas.car_model import ModelCreate, ModelUpdate


class ModelService(BaseService[Model, ModelCreate, ModelUpdate]):
    def __init__(self, session: AsyncSession):
        super().__init__(Model, session)

