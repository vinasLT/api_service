from sqlalchemy.ext.asyncio import AsyncSession

from auction_api.types.search import CommonSearchParams, CurrentSearchParams, HistorySearchParams
from core.logger import logger
from database.crud.car_make import MakeService
from database.crud.car_model import ModelService
from database.crud.damage import DamageService
from database.crud.document import DocumentService
from database.crud.drive import DriveService
from database.crud.status import StatusService
from database.crud.transmission import TransmissionService
from database.crud.vehicle_type import VehicleTypeService




async def transform_slugs(data: HistorySearchParams | CurrentSearchParams,
                          db: AsyncSession) -> HistorySearchParams | CurrentSearchParams:
    field_service_map = {
        'make': MakeService,
        'model': ModelService,
        'vehicle_type': VehicleTypeService,
        'transmission': TransmissionService,
        'status': StatusService,
        'drive': DriveService,
        'damage_pr': DamageService,
        'document': DocumentService
    }

    data_dict = data.model_dump()

    for field_name, field_value in data_dict.items():
        if field_name in field_service_map and field_value:
            service_class = field_service_map[field_name]
            service = service_class(db)

            try:
                obj = await service.get_by_field('slug', field_value)
                setattr(data, field_name, obj.name)
            except Exception as e:
                logger.warning(f"Error while transforming slugs for {field_name}", exception=e.__str__())
                pass

    return data






