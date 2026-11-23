from fastapi import APIRouter, Depends, Path
from fastapi_cache.decorator import cache
from rfc9457 import NotFoundProblem
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.crud.car_make import MakeService
from database.crud.car_model import ModelService
from database.db.session import get_async_db
from database.models import Damage, Document, Drive, Status, Transmission, VehicleType
from database.schemas.filters import FilterRead
from schemas.filters import AllFiltersOut
from services.http_cache import query_key_builder

filters_router = APIRouter()


async def _named_filters(model: type, db: AsyncSession) -> list[FilterRead]:
    rows = await BaseService(model, db).get_all_sorted("name")
    return [FilterRead.model_validate(row) for row in rows]


@filters_router.get("/all-filters", description='Get all static filters', response_model=AllFiltersOut)
@cache(expire=60*360, key_builder=query_key_builder)
async def filters(
        db: AsyncSession = Depends(get_async_db),
):
    return AllFiltersOut(
        damage=await _named_filters(Damage, db),
        document=await _named_filters(Document, db),
        drive=await _named_filters(Drive, db),
        status=await _named_filters(Status, db),
        transmission=await _named_filters(Transmission, db),
        vehicle_type=await _named_filters(VehicleType, db),
    )

@filters_router.get("/{vehicle_type_slug}/makes", description='Get all static filters', response_model=list[FilterRead])
async def filters(
        vehicle_type_slug: str = Path(..., description='Vehicle type slug'),
        db: AsyncSession = Depends(get_async_db),

):
    make_service = MakeService(db)
    vehicle_type = await BaseService(VehicleType, db).get_by_field('slug', vehicle_type_slug)
    if not vehicle_type:
        raise NotFoundProblem(detail="Vehicle type not found")

    makes = await make_service.get_makes_by_vehicle_type(vehicle_type)
    if not makes:
        return []
    return [FilterRead.model_validate(make_obj) for make_obj in makes]

@filters_router.get("/{vehicle_type_slug}/makes/{make_slug}/models",
                    description='Get all models by make and vehicle type',
                    response_model=list[FilterRead])
async def filters(
        vehicle_type_slug: str = Path(..., description='Vehicle type slug'),
        make_slug: str = Path(..., description='Make slug'),
        db: AsyncSession = Depends(get_async_db),
)-> list[FilterRead]:
    make_service = MakeService(db)
    model_service = ModelService(db)

    vehicle_type = await BaseService(VehicleType, db).get_by_field('slug', vehicle_type_slug)
    if not vehicle_type:
        raise NotFoundProblem(detail="Vehicle type not found")

    make = await make_service.get_make_by_slug_vehicle_type(make_slug, vehicle_type)
    if not make:
        raise NotFoundProblem(detail="Make not found")

    models = await model_service.get_by_make(make)
    return [FilterRead.model_validate(model_obj) for model_obj in models]
