import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select, update
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


def test_newer_update_revives_a_deleted_lot_without_a_delete_event(db):
    engine, session_factory = db
    key = ("2", 2)
    asyncio.run(
        upsert.save_lots([DBUpdateLot(lot_id=2, site=2, updated_at=OLD)], engine=engine)
    )
    deleted = DBDeleteLot(id="x", lot_id=2, site=2, created_at=OLD, updated_at=NEW)
    _, marked = asyncio.run(lots_sync._mark_deleted_lots([deleted]))
    assert marked == 1
    assert _rows(session_factory)[key].is_deleted is True

    later = DBUpdateLot(lot_id=2, site=2, vin="AGAIN", updated_at=NEW)
    assert asyncio.run(upsert.save_lots([later], engine=engine)) == 1
    row = _rows(session_factory)[key]
    assert (row.is_deleted, row.vin, row.deleted_at) == (False, "AGAIN", None)


def test_equal_update_revives_only_when_it_is_not_older_than_the_delete(db):
    engine, session_factory = db
    key = ("6", 1)
    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=6, site=1, vin="KEEP", updated_at=NEW)], engine=engine
        )
    )
    deleted = DBDeleteLot(id="x", lot_id=6, site=1, created_at=OLD, updated_at=NEW)
    _, marked = asyncio.run(lots_sync._mark_deleted_lots([deleted]))
    assert marked == 1

    same_age = DBUpdateLot(lot_id=6, site=1, vin="AGAIN", updated_at=NEW)
    assert asyncio.run(upsert.save_lots([same_age], engine=engine)) == 0
    assert _rows(session_factory)[key].is_deleted is True
    assert _rows(session_factory)[key].vin == "KEEP"

    assert asyncio.run(upsert.save_lots([same_age], {key: NEW}, engine=engine)) == 1
    row = _rows(session_factory)[key]
    assert (row.is_deleted, row.vin, row.deleted_at) == (False, "AGAIN", None)


def test_older_update_does_not_revive_a_deleted_lot(db):
    engine, session_factory = db
    key = ("3", 1)
    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=3, site=1, vin="KEEP", updated_at=OLD)], engine=engine
        )
    )
    deleted = DBDeleteLot(id="x", lot_id=3, site=1, created_at=OLD, updated_at=NEW)
    _, marked = asyncio.run(lots_sync._mark_deleted_lots([deleted]))
    assert marked == 1

    older = DBUpdateLot(lot_id=3, site=1, vin="STALE", updated_at=OLD)
    assert asyncio.run(upsert.save_lots([older], {key: NEW}, engine=engine)) == 0
    row = _rows(session_factory)[key]
    assert row.is_deleted is True
    assert row.vin == "KEEP"

    replacement = DBUpdateLot(lot_id=3, site=1, vin="BOOT", updated_at=NEW)
    assert asyncio.run(upsert.save_lots([replacement], engine=engine, replace=True)) == 1
    replaced = _rows(session_factory)[key]
    assert (replaced.is_deleted, replaced.vin) == (False, "BOOT")


def test_delete_older_than_the_stored_row_does_not_mark_it_deleted(db):
    engine, session_factory = db
    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=4, site=1, vin="LIVE", updated_at=NEW)], engine=engine
        )
    )
    deleted = DBDeleteLot(id="x", lot_id=4, site=1, created_at=OLD, updated_at=OLD)
    _, marked = asyncio.run(lots_sync._mark_deleted_lots([deleted]))

    row = _rows(session_factory)[("4", 1)]
    assert marked == 0
    assert row.is_deleted is False
    assert row.vin == "LIVE"


def _set_sale_status(session_factory, key: tuple[str, int], status: str) -> None:
    lot_id, site = key

    async def run():
        async with session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(SavedLots)
                    .where(SavedLots.lot_id == lot_id, SavedLots.site == site)
                    .values(sale_status=status, updated_at=SavedLots.updated_at)
                )

    asyncio.run(run())


def test_sold_lot_stays_deleted_when_the_current_feed_lists_it(db):
    engine, session_factory = db
    key = ("7", 1)
    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=7, site=1, vin="SOLD", updated_at=OLD)], engine=engine
        )
    )
    _set_sale_status(session_factory, key, "Sold")
    deleted = DBDeleteLot(id="x", lot_id=7, site=1, created_at=OLD, updated_at=NEW)
    _, marked = asyncio.run(lots_sync._mark_deleted_lots([deleted]))
    assert marked == 1

    later = DBUpdateLot(lot_id=7, site=1, vin="BACK", updated_at=NEW)
    assert asyncio.run(upsert.save_lots([later], engine=engine)) == 0
    assert asyncio.run(upsert.save_lots([later], {key: NEW}, engine=engine)) == 0
    assert asyncio.run(upsert.save_lots([later], engine=engine, undelete=True)) == 0

    row = _rows(session_factory)[key]
    assert row.is_deleted is True
    assert row.sale_status == "Sold"
    assert row.vin == "SOLD"


def test_undelete_restores_a_catalog_lot_without_rewriting_a_newer_body(db):
    engine, session_factory = db
    key = ("5", 1)
    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=5, site=1, vin="CURRENT", updated_at=NEW)],
            engine=engine,
        )
    )
    deleted = DBDeleteLot(id="x", lot_id=5, site=1, created_at=NEW, updated_at=NEW)
    _, marked = asyncio.run(lots_sync._mark_deleted_lots([deleted]))
    assert marked == 1

    same_age = DBUpdateLot(lot_id=5, site=1, vin="STALE", updated_at=NEW)
    assert asyncio.run(upsert.save_lots([same_age], engine=engine, undelete=True)) == 1
    row = _rows(session_factory)[key]
    assert row.is_deleted is False
    assert row.deleted_at is None
    assert row.vin == "CURRENT"

    newer = DBUpdateLot(lot_id=5, site=1, vin="FRESH", updated_at=datetime(2026, 12, 1, tzinfo=timezone.utc))
    assert asyncio.run(upsert.save_lots([newer], engine=engine, undelete=True)) == 1
    assert _rows(session_factory)[key].vin == "FRESH"


def test_purge_sold_pages_queries_keys_in_batches(db, monkeypatch):
    engine, _session_factory = db
    monkeypatch.setattr(lots_sync, "SQLITE_MAX_BIND_PARAMETERS", 4)
    monkeypatch.setattr(lots_sync, "cloudflare_configured", lambda: True)
    purged: list = []

    async def capture(rows):
        purged.extend(rows)

    monkeypatch.setattr(lots_sync, "purge_lot_urls", capture)

    statements: list[str] = []

    def before_cursor_execute(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "IN (" in statement and "saved_lots" in statement:
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before_cursor_execute)
    try:
        asyncio.run(
            upsert.save_lots(
                [
                    DBUpdateLot(
                        lot_id=index,
                        site=1,
                        base_site="copart",
                        year=2020,
                        make="Ford",
                        model="F150",
                        vin=f"VIN{index}",
                        updated_at=NEW,
                    )
                    for index in range(5)
                ],
                engine=engine,
            )
        )
        statements.clear()
        keys = {(str(index), 1) for index in range(5)}
        asyncio.run(lots_sync._purge_sold_pages(keys))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before_cursor_execute)

    assert len(statements) == 3
    assert {row.lot_id for row in purged} == {"0", "1", "2", "3", "4"}


def test_sale_result_columns_survive_feed_upserts():
    for column in (
        "sale_history",
        "sale_status",
        "sale_date",
        "purchase_price",
        "sale_history_fetched_at",
        "sale_count",
    ):
        assert column in upsert.EXCLUDED_COLUMNS
        assert column not in upsert.UPSERT_COLUMNS
    for sql in (
        upsert._merge_sql(replace=True),
        upsert._merge_sql(replace=False),
        upsert._merge_sql(replace=False, revive=True),
        upsert._merge_sql(replace=False, undelete=True),
    ):
        for column in (
            "sale_history",
            "sale_date",
            "purchase_price",
            "sale_history_fetched_at",
            "sale_count",
        ):
            assert f'EXCLUDED."{column}"' not in sql


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
