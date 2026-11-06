import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import jobs.lots_sync as lots_sync
import jobs.saved_lots_upsert as upsert
from auction_api.types.db_lot import DBDeleteLot, DBUpdateLot
from database.models import Base, SavedLots

OLD = datetime(2026, 10, 1, tzinfo=timezone.utc)
NEW = datetime(2026, 11, 1, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'lots.sqlite'}")
    session_factory = async_sessionmaker(
        engine, expire_on_commit=False, class_=AsyncSession
    )

    async def create_schema():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create_schema())
    monkeypatch.setattr(upsert, "AsyncSessionLocal", session_factory)
    monkeypatch.setattr(lots_sync, "AsyncSessionLocal", session_factory)
    yield engine, session_factory
    asyncio.run(engine.dispose())


def _rows(session_factory) -> dict[tuple[str, int], SavedLots]:
    async def fetch():
        async with session_factory() as session:
            rows = (await session.execute(select(SavedLots))).scalars().all()
            return {(row.lot_id, row.site): row for row in rows}

    return asyncio.run(fetch())


def test_save_lots_inserts_and_skips_stale_updates(db):
    engine, session_factory = db
    fresh = DBUpdateLot(
        lot_id=1,
        site=1,
        vin="NEW",
        link_img_hd=["https://img.example/1.jpg"],
        updated_at=NEW,
    )
    stale = DBUpdateLot(lot_id=1, site=1, vin="OLD", updated_at=OLD)

    assert asyncio.run(upsert.save_lots([fresh], engine=engine)) == 1
    assert asyncio.run(upsert.save_lots([stale], engine=engine)) == 0

    row = _rows(session_factory)[("1", 1)]
    assert row.vin == "NEW"
    assert row.link_img_hd == ["https://img.example/1.jpg"]
    assert row.is_deleted is False


def test_deleted_lots_are_not_resurrected_without_replace(db):
    engine, session_factory = db
    asyncio.run(
        upsert.save_lots([DBUpdateLot(lot_id=2, site=2, updated_at=OLD)], engine=engine)
    )
    deleted = DBDeleteLot(id="x", lot_id=2, site=2, created_at=OLD, updated_at=NEW)
    _, marked = asyncio.run(lots_sync._mark_deleted_lots([deleted]))
    assert marked == 1

    newer = DBUpdateLot(lot_id=2, site=2, vin="AGAIN", updated_at=NEW)
    assert asyncio.run(upsert.save_lots([newer], engine=engine)) == 0
    assert _rows(session_factory)[("2", 2)].is_deleted is True

    assert asyncio.run(upsert.save_lots([newer], engine=engine, replace=True)) == 1
    row = _rows(session_factory)[("2", 2)]
    assert (row.is_deleted, row.vin) == (False, "AGAIN")


def test_records_from_api_items_keeps_newest_per_lot():
    items = [
        {"lot_id": 7, "site": 1, "vin": "OLD", "updated_at": "2026-10-01T00:00:00"},
        {"lot_id": 7, "site": 1, "vin": "NEW", "updated_at": "2026-11-01T00:00:00"},
        {"lot_id": 8, "site": 2, "vin": "OTHER"},
    ]

    records = upsert.records_from_api_items(items)

    vin_index = upsert.UPSERT_COLUMNS.index("vin")
    assert [record[vin_index] for record in records] == ["NEW", "OTHER"]
    assert items == []
