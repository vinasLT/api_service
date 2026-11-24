# AGENTS.md

Instructions for coding agents working in this repository.

## What this is

Auction API service (`vinas-external-api-app`): a FastAPI HTTP API for current and history lots from Copart and IAAI, plus background jobs that sync lots, write sitemaps, and record job runs. Python 3.13, Poetry, SQLAlchemy (async), Alembic, Redis, and a small gRPC server.

Application code lives at the repository root. There is no `src/` package to import from.

## Commands

```bash
poetry install --no-root
poetry run pytest
poetry run uvicorn main:app --host 0.0.0.0 --port 8000
poetry run python serve_rpc.py
poetry run python -m jobs.scheduler
poetry run alembic upgrade head
poetry run alembic revision --autogenerate -m "describe the change"
```

CI installs with `poetry install --no-root` and runs `poetry run pytest` on Python 3.13. A pytest exit code of 5 (no tests collected) is treated as success.

`DEBUG=true` (the default, and what tests set) uses SQLite at `db.sqlite`. `DEBUG=false` uses Postgres from `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASS`. Alembic follows the same switch. Do not point a migration at production by accident.

Local Redis: `docker compose up redis`. The scheduler is opt-in: `docker compose --profile jobs up scheduler`. It forces `DEBUG=false` and `RUN_MIGRATIONS=false`, so it needs a reachable Postgres.

`AUCTION_API_KEY` is required. Tests set it in `tests/conftest.py`. Never commit `.env` or log provider API keys. Request headers that carry the key stay out of logs.

## Layout

| Path | Role |
| --- | --- |
| `main.py` | FastAPI app, lifespan (Redis cache), routers |
| `config.py` | `pydantic-settings`. `settings` is a module singleton |
| `routers/v1/` | HTTP handlers. Public under `/public/v1`, admin under `/admin/v1` |
| `routers/health.py` | Health checks |
| `request_schemas/`, `schemas/` | Pydantic models for query/body and responses |
| `auction_api/` | Client and types for the upstream auction provider |
| `basic_api/` | Shared HTTP client (`httpx`) used by `AuctionApiClient` |
| `dependencies/` | FastAPI dependencies, including the auction client |
| `services/` | Cache, provider usage, Cloudflare purge, slug transforms, job status, saved-lot reads |
| `database/models/` | SQLAlchemy models. Import new models from `database/models/__init__.py` so Alembic sees them |
| `database/crud/` | Async data access. Services take an `AsyncSession` |
| `database/db/session.py` | Engines and `get_async_db` |
| `jobs/` | Scheduler and job modules run as `python -m jobs.<module>` |
| `rpc_server/` | gRPC servicers. `serve_rpc.py` is the process entrypoint |
| `rpc_server/gen/` | Generated protobuf. Do not edit by hand |
| `alembic/versions/` | Migrations |
| `tests/` | pytest. `pythonpath` is the repo root |

Public routes (mounted in `main.py`):

- `/public/v1/lot/current` — current lots
- `/public/v1/lot/history` — history lots
- `/public/v1/filters`
- `/public/v1/lot/sales-history`
- `/public/v1/lot/similar-sales`
- `/public/v1/lot/title-indicators`
- `/public/v1/sitemaps`

Admin routes require `AuthTools` permission `api_service.seo_jobs.all:read` (`Permissions.SEO_JOBS` in `config.py`), via `require_permissions`.

Site values on public lot search: `1` / `copart`, `2` / `iaai`, or `all`. `auction_type=timed` is valid only for site `2`.

## How to change the code

- Add an HTTP endpoint as a router in `routers/v1/`, then `include_router` it from `main.py` on the public or admin router. Keep handlers thin: validate with Pydantic, call a service or `AuctionApiClient`, return a response model.
- Validate query params with a Pydantic model and `Query(...)`, matching `routers/v1/lots.py`.
- Raise `rfc9457` problems (`NotFoundProblem`, `ConflictProblem`, `BadRequestProblem`). The app installs `fastapi-problem` handlers in `main.py`. Do not invent a second error shape.
- Use `get_async_db` for request-scoped sessions. Do not open a global session in a router.
- Cache public GETs with `@cache` from `fastapi_cache` and `query_key_builder` in `services/http_cache.py` when the response is safe to share. Admin routes are not cached.
- Log with `core.logger.logger` (loguru, one JSON object per line). Pass context as `extra={...}`. Do not print secrets.
- Register a new permission on `Permissions` in `config.py` and declare it on the route with `require_permissions`. Mention the permission in the route `description`.
- Provider calls go through `AuctionApiClient` / `BaseClient`. Add an upstream endpoint as an `Endpoint` plus an `EndpointSchema` on the client. Do not call the provider with a raw `httpx` client from a router.

### Database

- Models subclass `database.models.base.Base`. Export them from `database.models/__init__.py`.
- Schema changes need an Alembic revision. Prefer autogenerate, then read the file and delete unrelated operations. Keep revisions compatible with both SQLite (local/`DEBUG`) and Postgres (jobs and production). Avoid Postgres-only types unless the change is jobs-only and tested against Postgres.
- Job-run writes in `jobs/job_runs.py` use the sync engine. HTTP handlers use the async session. Do not mix them in one code path.

### Saved lots

`saved_lots` is the local catalog. Current lots are written by `jobs/lots_full_load.py` and `jobs/lots_sync.py` through `save_lots` in `jobs/saved_lots_upsert.py`. That writer inserts rows with `is_deleted` false and leaves sale columns alone. `EXCLUDED_COLUMNS` is `sale_history`, `sale_status`, `sale_date`, `purchase_price`, `sale_history_fetched_at`, and `sale_count`. Archival writes go through `services/saved_lots_read.py` on the request `AsyncSession`. gRPC opens `AsyncSessionLocal` and calls the same helpers. A database error is logged and swallowed so the provider payload is still returned.

Hourly sync treats `db/cars/deleted` as an event. It marks a stored row deleted only when that event is newer than the row's `updated_at`. A current-feed update clears `is_deleted` when it is newer than the stored row, including after the delete event has left the lookback window. An update from the same run that is only the same age as the delete event also clears it. Weekly verify (`FullLoadMode.VERIFY`) clears `is_deleted` for every lot still present in `db/cars/all`, even when `updated_at` is unchanged, and still does not rewrite sale columns. A stored `sale_status` of `sold` is left deleted by both jobs. A lot that has left the current catalog stays deleted. A non-deleted row is returned as active. Its top-level `sale_status`, `sale_date`, and `purchase_price` are omitted unless that status is `sold`, so a "Not sold" attempt is not shown as the final sale. `sale_history` stays, and a deleted row stays history.

Catalog lookup checks `saved_lots` first, including when `site` is `all`. A hit does not call the provider. On a miss, a lot id uses `AuctionApiClient.GET_LOT_BY_ID_FOR_WEB` (`GET /cars/lot-id/web`) once. `site=all` is accepted on that lookup and omitted from the provider query. A VIN uses `GET /cars/vin` and, only on 404, `GET /cars/vin/all`. `get_lot_vin_or_lot_id` is that order for HTTP and gRPC. An empty web result is not-found. Do not call `GET /cars/{lotId}` from lookup. `store_catalog_lot` writes `sale_count` on a row that already exists and does not insert a row, so a catalog miss cannot schedule a later `sale-histories` call.

Full sale lists stay on `GET /sale-histories/lot-id` and `GET /sale-histories/vin` (`GET_LOT_HISTORY_BY_ID`, `GET_LOT_HISTORY_BY_VIN`). History search sends `size` of at most 25. Similar-sale prices use `GET /history-cars/statistic` with `period=6`, not `GET /history-cars`. The history-by-id, history-by-vin, and sales-history miss paths, plus gRPC `GetSaleHistory`, call `store_archival_lots`. That writes `sale_history`, `sale_status`, `sale_date`, `purchase_price`, and `sale_history_fetched_at`. A missing row is inserted archived. An existing row, including one that is still active, keeps `is_deleted` and the current-feed columns. gRPC `GetLot` calls `sale-histories/lot-id` only for a deleted feed row whose `sale_history_fetched_at` is unset. Lot lookup, sale history, and averages share `cached_provider_call`. The gRPC Redis cache remains for the current bid and the current-lot list.

`sale_count` is optional on `BasicHistoryLot`. `prepare_web_response` copies an integer from `sale_count`, `sales_count`, `sale_histories_count`, or `count`. The generated gRPC `Lot` message has no such field, so `sale_count` stays in `LotRpc._LOT_PROTO_EXCLUDE_FIELDS`.

The sold sitemap streams every `is_deleted` row, so a history-only insert shows up there. A still-active lot stays out of that set.

### Jobs

The scheduler (`jobs/scheduler.py`) runs in `Europe/Vilnius` and starts each job as a subprocess: `python -m <module>`. Scheduled jobs today: lots full load (bootstrap and weekly verify), hourly lots sync, sitemap every 3 hours. Manual runs are queued in `job_runs` and polled by the scheduler.

- New scheduled work is a module with a `main()`, a `JobSpec` in `scheduled_jobs()`, and a timeout. The scheduler skips a job when that job id is already running.
- Long sync and sitemap work must stay idempotent. Locks live in `jobs/locks.py`.
- Record outcomes through `jobs/job_runs.py` (`start_run`, `record_outcome`, `finish_run`). Do not write job status only to logs.

### gRPC

`rpc_server/gen/` is produced from `buf.build/vinaslt/main` via `rpc_server/buf.gen.yaml`. Change the API in the protobuf repo and regenerate. Do not patch `*_pb2.py` or `*_pb2_grpc.py`.

## Tests

Tests are plain pytest, no pytest-asyncio plugin. Async DB setup uses `asyncio.run` or an async fixture that the test drives itself. Follow `tests/test_admin_jobs_router.py`:

- Override `get_async_db` (and `get_user` for admin routes) on `app.dependency_overrides`.
- Use an in-memory SQLite engine with `StaticPool` when the handler needs a database.
- Clear overrides after the test.
- Freeze clocks by monkeypatching the function the code calls (for example `services.job_status._now`), not by sleeping.

Run the nearest test file before finishing a change: `poetry run pytest tests/test_<area>.py`.

## Do not

- Commit `.env`, `db.sqlite`, or credentials.
- Edit generated files under `rpc_server/gen/`.
- Log `AUCTION_API_KEY`, AWS keys, or Cloudflare tokens.
- Add a new HTTP framework, ORM, or migration tool.
- Enable docs outside development. `settings.enable_docs` is true only when `ENVIRONMENT=development`.
