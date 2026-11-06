from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

SAVED_LOTS_WRITE_LOCK = "saved_lots_write"

_TRY_LOCK_SQL = text("SELECT pg_try_advisory_lock(hashtext(:name))")
_UNLOCK_SQL = text("SELECT pg_advisory_unlock(hashtext(:name))")


@asynccontextmanager
async def advisory_lock(engine: AsyncEngine, name: str) -> AsyncIterator[bool]:
    """Yield True if this process now holds the session-level advisory lock `name`.

    Pass `engine_async`, not the save engine: the lock connection sits idle for the
    whole job and must not be cut by `idle_in_transaction_session_timeout`.
    """
    if engine.dialect.name != "postgresql":
        yield True
        return

    async with engine.connect() as conn:
        acquired = (await conn.execute(_TRY_LOCK_SQL, {"name": name})).scalar_one()
        await conn.commit()
        try:
            yield bool(acquired)
        finally:
            if acquired:
                await conn.execute(_UNLOCK_SQL, {"name": name})
                await conn.commit()
