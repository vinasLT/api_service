"""Cache of upstream auction-provider responses, shared by every route that calls the same endpoint."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from rfc9457 import NotFoundProblem

from auction_api.api import EndpointSchema
from auction_api.types.lot import BasicHistoryLot
from core.logger import logger
from services.provider_usage import is_crawler
from services.redis_client import get_redis

TTL_NOT_FOUND = 12 * 60 * 60
TTL_SALE_HISTORY_SOLD = 30 * 24 * 60 * 60
TTL_SALE_HISTORY_UNSOLD = 6 * 60 * 60
TTL_HISTORY_CARS_SIMILAR = 7 * 24 * 60 * 60
TTL_HISTORY_CARS_LISTING = 60 * 60

_LOCK_SECONDS = 15
_WAIT_ATTEMPTS = 25
_WAIT_SECONDS = 0.2
_NOT_FOUND = "not_found"
_OK = "ok"


def cache_key(endpoint: str, data: BaseModel) -> str:
    payload = data.model_dump(exclude_none=True, mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return f"prov:{endpoint}:{canonical}"


def is_sold_history(result: Any) -> bool:
    if isinstance(result, list):
        return any(is_sold_history(item) for item in result)
    if getattr(result, "purchase_price", None) or getattr(result, "sale_date", None):
        return True
    return bool(getattr(result, "sale_history", None))


def sale_history_ttl(result: Any) -> int:
    if is_sold_history(result):
        return TTL_SALE_HISTORY_SOLD
    return TTL_SALE_HISTORY_UNSOLD


def _log(endpoint: str, cache_result: str) -> None:
    logger.info(
        "Provider cache {}",
        cache_result,
        extra={
            "data": {
                "endpoint": endpoint,
                "cache_result": cache_result,
                "is_bot": is_crawler.get(),
            }
        },
    )


def _serialize(result: Any) -> Any:
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    if isinstance(result, list):
        return [_serialize(item) for item in result]
    return result


def _deserialize(schema: EndpointSchema, body: Any) -> Any:
    if schema.is_pagination and schema.pagination_schema and isinstance(body, dict):
        item_schema = schema.out_schema_history or schema.out_schema_default
        items = [item_schema.model_validate(item) for item in body.get("data") or []]
        return schema.pagination_schema.model_construct(
            size=body.get("size") or 0,
            page=body.get("page") or 0,
            pages=body.get("pages") or 0,
            count=body.get("count") or 0,
            data=items,
        )

    model = schema.out_schema_history or schema.out_schema_default
    if isinstance(body, list):
        restored = [model.model_validate(item) for item in body]
        return restored[0] if len(restored) == 1 else restored
    if isinstance(body, dict) and schema.out_schema_history is BasicHistoryLot:
        return BasicHistoryLot.model_validate(body)
    return model.model_validate(body)


async def _read(key: str) -> dict | None:
    client = get_redis()
    if client is None:
        return None
    try:
        raw = await client.get(key)
    except Exception as exc:
        logger.warning(f"Provider cache read failed: {exc}")
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def _write(key: str, payload: dict, ttl: int) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(payload, default=str).encode(), ex=ttl)
    except Exception as exc:
        logger.warning(f"Provider cache write failed: {exc}")


async def _acquire_lock(key: str) -> bool:
    client = get_redis()
    if client is None:
        return True
    try:
        acquired = await client.set(f"{key}:lock", b"1", nx=True, ex=_LOCK_SECONDS)
    except Exception as exc:
        logger.warning(f"Provider cache lock failed: {exc}")
        return True
    return bool(acquired)


async def _release_lock(key: str) -> None:
    client = get_redis()
    if client is None:
        return
    try:
        await client.delete(f"{key}:lock")
    except Exception as exc:
        logger.warning(f"Provider cache unlock failed: {exc}")


def _unpack(schema: EndpointSchema, cached: dict) -> Any:
    if cached.get("kind") == _NOT_FOUND:
        raise NotFoundProblem("Lot not found")
    return _deserialize(schema, cached.get("body"))


async def cached_provider_call(
    api: Any,
    schema: EndpointSchema,
    data: BaseModel,
    *,
    ttl: int | Callable[[Any], int],
    request_kwargs: dict | None = None,
) -> Any:
    """Return a cached provider response, fetching it once when several callers arrive together."""
    endpoint = schema.endpoint.value
    key = cache_key(endpoint, data)
    cached = await _read(key)
    if cached is not None:
        _log(endpoint, "hit")
        return _unpack(schema, cached)

    owns_lock = await _acquire_lock(key)
    if not owns_lock:
        for _ in range(_WAIT_ATTEMPTS):
            await asyncio.sleep(_WAIT_SECONDS)
            cached = await _read(key)
            if cached is not None:
                _log(endpoint, "hit")
                return _unpack(schema, cached)
        owns_lock = await _acquire_lock(key)

    try:
        cached = await _read(key)
        if cached is not None:
            _log(endpoint, "hit")
            return _unpack(schema, cached)

        try:
            result = await api.request_with_schema(schema, data, **(request_kwargs or {}))
        except NotFoundProblem:
            await _write(key, {"kind": _NOT_FOUND}, TTL_NOT_FOUND)
            _log(endpoint, "miss")
            raise

        expire = ttl(result) if callable(ttl) else ttl
        await _write(key, {"kind": _OK, "body": _serialize(result)}, expire)
        return result
    finally:
        if owns_lock:
            await _release_lock(key)
