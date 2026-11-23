from typing import Union

from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.types.search import CurrentSearchParams, HistorySearchParams
from core.logger import logger
from database.crud.base import BaseService
from database.models import Damage, Document, Drive, Make, Model, Status, Transmission, VehicleType


_FIELD_MODELS = {
    'make': Make,
    'model': Model,
    'vehicle_type': VehicleType,
    'transmission': Transmission,
    'status': Status,
    'drive': Drive,
    'damage_pr': Damage,
    'document': Document,
}


async def transform_slugs(
    data: Union[HistorySearchParams, CurrentSearchParams],
    db: AsyncSession
) -> Union[HistorySearchParams, CurrentSearchParams]:
    data_dict = data.model_dump()

    for field_name, field_value in data_dict.items():
        model = _FIELD_MODELS.get(field_name)
        if model is None or field_value in (None, '', [], ()):
            continue

        service = BaseService(model, db)
        is_list = isinstance(field_value, (list, tuple, set))
        values = list(field_value) if is_list else [field_value]

        transformed = []
        for value in values:
            try:
                obj = await service.get_by_field('slug', value)
                transformed.append(obj.name if obj else value)
            except Exception as e:
                logger.exception(f"Error while transforming slugs for {field_name}", exception=e.__str__())
                transformed.append(value)

        setattr(data, field_name, transformed if is_list else transformed[0])

    logger.debug(f"Transformed slugs: {data}")
    return data
