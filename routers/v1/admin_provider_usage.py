from AuthTools.Permissions.dependencies import require_permissions
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from config import Permissions
from services.provider_usage import read_provider_usage

admin_provider_usage_router = APIRouter()


class ProviderEndpointUsage(BaseModel):
    endpoint: str
    calls: int


class ProviderUsageOut(BaseModel):
    date: str
    endpoints: list[ProviderEndpointUsage]


@admin_provider_usage_router.get(
    "",
    response_model=ProviderUsageOut,
    dependencies=[Depends(require_permissions(Permissions.SEO_JOBS))],
    description=(
        "Provider call counters for one UTC day. "
        f"Required permissions: {Permissions.SEO_JOBS.value}"
    ),
)
async def provider_usage(date: str | None = None) -> dict:
    return await read_provider_usage(date)
