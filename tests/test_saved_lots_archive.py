import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import jobs.saved_lots_upsert as upsert
from auction_api.api import AuctionApiClient
from auction_api.types.db_lot import DBUpdateLot
from auction_api.types.lot import BasicHistoryLot, BasicLot, FormGetType, SaleHistoryItem
from database.models import Base, SavedLots
from services.saved_lots_read import (
    sales_from_row,
    saved_lot_to_model,
    store_archival_lots,
    store_catalog_lot,
)

FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)
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
    yield engine, session_factory
    asyncio.run(engine.dispose())


def _rows(session_factory) -> dict[tuple[str, int], SavedLots]:
    async def fetch():
        async with session_factory() as session:
            rows = (await session.execute(select(SavedLots))).scalars().all()
            return {(row.lot_id, row.site): row for row in rows}

    return asyncio.run(fetch())


def _store(session_factory, store, lot):
    async def run():
        async with session_factory() as session:
            await store(session, lot)

    asyncio.run(run())


def test_catalog_history_without_a_row_inserts_nothing(db):
    _, session_factory = db
    _store(
        session_factory,
        store_catalog_lot,
        BasicHistoryLot(lot_id=21, site=1, vin="HIST", sale_count=7),
    )

    assert _rows(session_factory) == {}


def test_web_result_fills_sale_count_on_an_active_row(db):
    engine, session_factory = db
    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=12, site=1, vin="FEED", updated_at=NEW)],
            engine=engine,
        )
    )
    lot = BasicHistoryLot(
        lot_id=12,
        site=1,
        vin="OTHER",
        auction_date=FUTURE,
        sale_count=4,
    )
    assert lot.form_get_type is FormGetType.ACTIVE

    _store(session_factory, store_catalog_lot, lot)

    row = _rows(session_factory)[("12", 1)]
    assert row.is_deleted is False
    assert row.vin == "FEED"
    assert row.sale_count == 4
    assert row.sale_history_fetched_at is None


def test_active_web_response_still_writes_sale_count(db):
    engine, session_factory = db
    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=12, site=1, vin="FEED", updated_at=NEW)],
            engine=engine,
        )
    )
    lot = AuctionApiClient().process_response(
        {
            "lot_id": 12,
            "site": 1,
            "vin": "LIVE",
            "form_get_type": "active",
            "sale_count": 4,
        },
        AuctionApiClient.GET_LOT_BY_ID_FOR_WEB,
    )
    assert type(lot) is BasicLot

    _store(session_factory, store_catalog_lot, lot)

    row = _rows(session_factory)[("12", 1)]
    assert row.is_deleted is False
    assert row.vin == "FEED"
    assert row.sale_count == 4


def test_active_web_result_without_a_row_inserts_nothing(db):
    _, session_factory = db
    lot = BasicHistoryLot(
        lot_id=30,
        site=1,
        vin="LIVE",
        auction_date=FUTURE,
        sale_count=4,
    )
    assert lot.form_get_type is FormGetType.ACTIVE

    _store(session_factory, store_catalog_lot, lot)

    assert _rows(session_factory) == {}


def test_web_payload_count_aliases_land_on_sale_count():
    client = AuctionApiClient()
    schema = AuctionApiClient.GET_LOT_BY_ID_FOR_WEB

    from_sales_count = client.process_response(
        {"lot_id": 1, "site": 1, "vin": "A", "sales_count": 6},
        schema,
    )
    from_count = client.process_response(
        {"lot_id": 2, "site": 1, "vin": "B", "count": 3},
        schema,
    )
    from_histories_count = client.process_response(
        {"lot_id": 4, "site": 1, "vin": "D", "sale_histories_count": 8},
        schema,
    )
    missing = client.process_response(
        {"lot_id": 3, "site": 1, "vin": "C", "make": "Ford"},
        schema,
    )

    assert from_sales_count.sale_count == 6
    assert from_count.sale_count == 3
    assert from_histories_count.sale_count == 8
    assert missing.sale_count is None

    active = client.process_response(
        {
            "lot_id": 5,
            "site": 1,
            "vin": "E",
            "form_get_type": "active",
            "sale_count": 4,
        },
        schema,
    )
    assert type(active) is BasicLot
    assert active.form_get_type is FormGetType.ACTIVE
    assert active.sale_count == 4


def test_sale_history_insert_dedupes_and_keeps_an_active_row_active(db):
    engine, session_factory = db
    history = BasicHistoryLot(
        lot_id=3,
        site=2,
        vin="SOLD",
        sale_status="Sold",
        purchase_price=1000,
        sale_history=[SaleHistoryItem(lot_id=3, site=2, purchase_price=1000, sale_status="Sold")],
    )

    _store(session_factory, store_archival_lots, history)
    _store(session_factory, store_archival_lots, history)

    rows = _rows(session_factory)
    stored = rows[("3", 2)]
    assert list(rows) == [("3", 2)]
    assert stored.is_deleted is True
    assert stored.sale_status == "Sold"
    assert stored.purchase_price == 1000
    assert stored.sale_history_fetched_at is not None
    assert stored.sale_history[0]["purchase_price"] == 1000

    asyncio.run(
        upsert.save_lots(
            [DBUpdateLot(lot_id=4, site=1, vin="FEED", updated_at=NEW)],
            engine=engine,
        )
    )
    _store(
        session_factory,
        store_archival_lots,
        BasicHistoryLot(lot_id=4, site=1, vin="OTHER", sale_status="Sold", purchase_price=9),
    )

    active = _rows(session_factory)[("4", 1)]
    assert active.is_deleted is False
    assert active.vin == "FEED"
    assert active.sale_status == "Sold"
    assert active.purchase_price == 9
    assert active.sale_history_fetched_at is not None


def test_lot_missing_site_is_skipped(db):
    _, session_factory = db
    _store(session_factory, store_archival_lots, BasicHistoryLot(lot_id=5, vin="X"))
    assert _rows(session_factory) == {}


def test_store_failure_is_swallowed(monkeypatch):
    class Session:
        def __init__(self):
            self.rolled_back = False

        async def rollback(self):
            self.rolled_back = True

    session = Session()

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("services.saved_lots_read.find_saved_lot", boom)
    asyncio.run(store_archival_lots(session, BasicHistoryLot(lot_id=1, site=1, vin="X")))
    assert session.rolled_back is True


def test_active_buy_now_with_a_not_sold_attempt_stays_active():
    past = datetime(2026, 11, 23, 19, 16, tzinfo=timezone.utc)
    history = [
        {
            "lot_id": 67009726,
            "site": 1,
            "sale_status": "Not sold",
            "sale_date": past.isoformat(),
            "purchase_price": 5000,
            "is_buynow": False,
        }
    ]
    row = SavedLots(
        lot_id="67009726",
        site=1,
        is_buynow=True,
        price_new=8200,
        current_bid=575,
        auction_date=past,
        is_deleted=False,
        sale_status="Not sold",
        sale_date=past,
        purchase_price=5000,
        sale_history=history,
    )

    lot = saved_lot_to_model(row)

    assert lot.form_get_type is FormGetType.ACTIVE
    assert lot.is_buynow is True
    assert lot.price_new == 8200
    assert lot.auction_date == past
    assert lot.sale_status is None
    assert lot.sale_date is None
    assert lot.purchase_price is None
    sales = sales_from_row(row)
    assert [(sale.status, sale.final_bid) for sale in sales] == [("Not sold", 5000)]


def test_active_sold_row_keeps_its_sale_result():
    past = datetime(2026, 11, 23, 19, 16, tzinfo=timezone.utc)
    row = SavedLots(
        lot_id="8",
        site=1,
        auction_date=past,
        is_deleted=False,
        sale_status="Sold",
        sale_date=past,
        purchase_price=5000,
    )

    lot = saved_lot_to_model(row)

    assert lot.form_get_type is FormGetType.ACTIVE
    assert lot.sale_status == "Sold"
    assert lot.sale_date == past
    assert lot.purchase_price == 5000


def test_deleted_row_stays_history_with_its_sale_result():
    past = datetime(2026, 11, 23, 19, 16, tzinfo=timezone.utc)
    row = SavedLots(
        lot_id="9",
        site=1,
        auction_date=past,
        is_deleted=True,
        sale_status="Sold",
        sale_date=past,
        purchase_price=5000,
    )

    lot = saved_lot_to_model(row)

    assert lot.form_get_type is FormGetType.HISTORY
    assert lot.auction_date is None
    assert lot.sale_status == "Sold"
    assert lot.sale_date == past
    assert lot.purchase_price == 5000


def test_sale_count_is_absent_from_current_lot_merge_sql():
    assert "sale_count" in upsert.EXCLUDED_COLUMNS
    assert "sale_count" not in upsert.UPSERT_COLUMNS
    assert "sale_count" not in upsert._merge_sql(replace=True)
    assert "sale_count" not in upsert._merge_sql(replace=False)
