"""Shared async Redis client for the HTTP API process."""

from redis.asyncio import Redis

from config import settings

_client: Redis | None = None


def get_redis() -> Redis | None:
    return _client


def set_redis(client: Redis | None) -> None:
    global _client
    _client = client


async def init_redis() -> Redis:
    client = Redis.from_url(settings.REDIS_URL)
    set_redis(client)
    return client


async def close_redis() -> None:
    client = get_redis()
    set_redis(None)
    if client is None:
        return
    closer = getattr(client, "aclose", None) or getattr(client, "close", None)
    if closer is not None:
        await closer()
