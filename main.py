from contextlib import asynccontextmanager

import uvicorn
from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_problem.handler import add_exception_handler, new_exception_handler

from config import settings
from core.logger import logger
from routers.health import health_router
from routers.v1.admin_jobs import admin_jobs_router
from routers.v1.admin_provider_usage import admin_provider_usage_router
from routers.v1.filters import filters_router
from routers.v1.history_lots import history_cars_router
from routers.v1.lots import cars_router
from routers.v1.sales_history import sales_history_router
from routers.v1.saved_lots import saved_lots_router
from routers.v1.similar_archived_sales import similar_sales_router
from routers.v1.sitemaps import sitemaps_router
from routers.v1.title_indicators import title_indicators_router
from services import redis_client
from services.provider_usage import is_crawler

_API_ROBOTS = "User-agent: *\nDisallow: /auction-api/\n"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        cache_redis = await redis_client.init_redis()
        FastAPICache.init(RedisBackend(cache_redis), prefix="fastapi-cache")
    except Exception:
        logger.exception("Redis cache is unavailable; provider calls will not be cached")
    yield
    await redis_client.close_redis()


docs_url = "/docs" if settings.enable_docs else None
redoc_url = "/redoc"  if settings.enable_docs else None
openapi_url = "/openapi.json" if settings.enable_docs else None
app = FastAPI(lifespan=lifespan,
              root_path=settings.ROOT_PATH,
              title="Auction Api Service",
              description="IAAI COPART Auctions API",
              version="0.0.1",
              docs_url=docs_url,
              redoc_url=redoc_url,
              openapi_url=openapi_url,
              )

eh = new_exception_handler()
add_exception_handler(app, eh)


@app.middleware("http")
async def mark_crawler_requests(request: Request, call_next):
    token = is_crawler.set(request.headers.get("x-crawler") == "1")
    try:
        return await call_next(request)
    finally:
        is_crawler.reset(token)


@app.get("/robots.txt", include_in_schema=False)
async def api_robots():
    return PlainTextResponse(_API_ROBOTS)


public_v1_router = APIRouter(prefix="/public/v1")

public_v1_router.include_router(cars_router, prefix='/lot/current', tags=["Public Current Lots"])
public_v1_router.include_router(saved_lots_router, prefix='/lot', tags=["Saved Lots"])
public_v1_router.include_router(history_cars_router, prefix='/lot/history', tags=["Public History Lots"])

public_v1_router.include_router(filters_router, prefix='/filters', tags=["Filters"])

public_v1_router.include_router(sales_history_router, prefix='/lot/sales-history', tags=["Sales History"])

public_v1_router.include_router(similar_sales_router, prefix='/lot/similar-sales', tags=["Similar Sales"])

public_v1_router.include_router(title_indicators_router, prefix='/lot/title-indicators', tags=["Title Indicators"])

public_v1_router.include_router(sitemaps_router, prefix='/sitemaps', tags=["Sitemaps"])
app.include_router(public_v1_router)

admin_v1_router = APIRouter(prefix="/admin/v1")
admin_v1_router.include_router(admin_jobs_router, prefix="/jobs", tags=["Admin Jobs"])
admin_v1_router.include_router(
    admin_provider_usage_router, prefix="/provider-usage", tags=["Provider Usage"]
)
app.include_router(admin_v1_router)

app.include_router(health_router, tags=["Health"])



if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=8001)




