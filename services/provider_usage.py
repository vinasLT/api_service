"""Counts real calls to the auction provider, including which ones came from crawlers."""

from contextvars import ContextVar
from datetime import datetime, timezone

from core.logger import logger
from services.redis_client import get_redis

is_crawler: ContextVar[bool] = ContextVar("is_crawler", default=False)

RETENTION_SECONDS = 14 * 24 * 60 * 60
CALLS_PREFIX = "provider:calls"
BOT_CALLS_PREFIX = "provider:bot-calls"


def _day(day: str | None = None) -> str:
    return day or datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _calls_key(day: str, endpoint: str) -> str:
    return f"{CALLS_PREFIX}:{day}:{endpoint}"


def _bot_calls_key(day: str, endpoint: str) -> str:
    return f"{BOT_CALLS_PREFIX}:{day}:{endpoint}"


def _decode(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return value


async def record_provider_call(endpoint: str) -> None:
    """Increment today's counter for one provider call. Never raises."""
    client = get_redis()
    if client is None:
        return

    day = _day()
    total_key = _calls_key(day, endpoint)
    try:
        pipe = client.pipeline()
        pipe.incr(total_key)
        pipe.expire(total_key, RETENTION_SECONDS)
        if is_crawler.get():
            bot_key = _bot_calls_key(day, endpoint)
            pipe.incr(bot_key)
            pipe.expire(bot_key, RETENTION_SECONDS)
        await pipe.execute()
    except Exception as exc:
        logger.warning(f"Failed to record provider call: {exc}")


async def _counter(key: str) -> int:
    client = get_redis()
    if client is None:
        return 0
    raw = await client.get(key)
    if raw is None:
        return 0
    return int(_decode(raw) or 0)


async def _endpoints_for(prefix: str, day: str) -> dict[str, int]:
    client = get_redis()
    if client is None:
        return {}

    pattern = f"{prefix}:{day}:*"
    marker = f"{prefix}:{day}:"
    counts: dict[str, int] = {}
    async for key in client.scan_iter(match=pattern, count=200):
        decoded = _decode(key)
        endpoint = decoded.removeprefix(marker)
        if not endpoint:
            continue
        counts[endpoint] = await _counter(decoded)
    return counts


async def read_provider_usage(day: str | None = None) -> dict:
    usage_day = _day(day)
    totals = await _endpoints_for(CALLS_PREFIX, usage_day)
    bots = await _endpoints_for(BOT_CALLS_PREFIX, usage_day)
    endpoints = [
        {
            "endpoint": endpoint,
            "calls": totals.get(endpoint, 0),
            "bot_calls": bots.get(endpoint, 0),
        }
        for endpoint in sorted(set(totals) | set(bots))
    ]
    return {"date": usage_day, "endpoints": endpoints}
