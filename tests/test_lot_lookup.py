import asyncio
import os
import sys
from datetime import datetime, timezone

import pytest
from rfc9457 import BadRequestProblem, NotFoundProblem
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rpc_server", "gen", "python"))

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicHistoryLot, BasicLot
from auction_api.types.search import CurrentSearchParams
from auction_api.utils import get_lot_vin_or_lot_id
from basic_api.base_client import provider_params
from database.models.saved_lots import SavedLots
from request_schemas.lot import LotByIDIn
from services.saved_lots_read import find_saved_lots_by_vin
from rpc_server.gen.python.auction.v1 import lot_pb2
from rpc_server.lot_rpc import LotRpc
from services.redis_client import set_redis


class FakeRedis:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.store:
            return False
        if isinstance(value, str):
            value = value.encode()
        self.store[key] = value
        return True

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


class _Context:
    def __init__(self):
        self.code = None
        self.details = None

    def set_code(self, code):
        self.code = code

    def set_details(self, details):
        self.details = details


class RecordingApi:
    def __init__(self, handler):
        self.calls: list[tuple[str, dict]] = []
        self.handler = handler
        self.GET_LOT_BY_ID_FOR_WEB = AuctionApiClient.GET_LOT_BY_ID_FOR_WEB
        self.GET_LOT_BY_VIN_FOR_CURRENT = AuctionApiClient.GET_LOT_BY_VIN_FOR_CURRENT
        self.GET_LOT_BY_VIN_FOR_ALL_TIME = AuctionApiClient.GET_LOT_BY_VIN_FOR_ALL_TIME

    async def request_with_schema(self, schema, data, **kwargs):
        self.calls.append((schema.endpoint.value, data.model_dump(exclude_none=True)))
        return await self.handler(schema, data)


@pytest.fixture
def fake_redis():
    fake = FakeRedis()
    set_redis(fake)
    yield fake
    set_redis(None)


def _endpoints(api: RecordingApi) -> list[str]:
    return [endpoint for endpoint, _payload in api.calls]


def test_lot_id_calls_web_only(fake_redis):
    async def handler(schema, data):
        return AuctionApiClient().process_response(
            {"lot_id": data.lot_id, "site": 1, "vin": "WEB"},
            schema,
        )

    api = RecordingApi(handler)

    async def run():
        return await get_lot_vin_or_lot_id(api, "1", "21")

    lot = asyncio.run(run())
    assert lot.lot_id == 21
    assert _endpoints(api) == ["cars/lot-id/web"]


def test_current_vin_hit_does_not_call_all_time(fake_redis):
    async def handler(schema, data):
        return BasicLot(lot_id=5, site=1, vin=data.vin)

    api = RecordingApi(handler)

    async def run():
        return await get_lot_vin_or_lot_id(api, "1", "1hgcm82633a004352")

    lot = asyncio.run(run())
    assert lot.vin == "1HGCM82633A004352"
    assert _endpoints(api) == ["cars/vin"]
    assert "site" not in api.calls[0][1]


def test_vin_not_found_falls_through_to_all_time(fake_redis):
    async def handler(schema, data):
        if schema.endpoint.value == "cars/vin":
            raise NotFoundProblem("Lot not found")
        return BasicHistoryLot(lot_id=5, site=1, vin=data.vin)

    api = RecordingApi(handler)

    async def run():
        return await get_lot_vin_or_lot_id(api, "1", "1hgcm82633a004352")

    lot = asyncio.run(run())
    assert lot.lot_id == 5
    assert _endpoints(api) == ["cars/vin", "cars/vin/all"]
    assert api.calls[1][1]["site"] == "1"


def test_lot_id_site_all_calls_web_and_drops_site_for_the_provider(fake_redis):
    async def handler(schema, data):
        return AuctionApiClient().process_response(
            {"lot_id": data.lot_id, "site": 1, "vin": "WEB", "form_get_type": "active"},
            schema,
        )

    api = RecordingApi(handler)

    async def run():
        return await get_lot_vin_or_lot_id(api, "all", "21")

    lot = asyncio.run(run())
    assert type(lot) is BasicLot
    assert lot.form_get_type == "active"
    assert _endpoints(api) == ["cars/lot-id/web"]
    forwarded = provider_params(AuctionApiClient.GET_LOT_BY_ID_FOR_WEB, LotByIDIn(lot_id=21, site="all"))
    assert "site" not in forwarded
    numbered = provider_params(AuctionApiClient.GET_LOT_BY_ID_FOR_WEB, LotByIDIn(lot_id=21, site="3"))
    assert "site" not in numbered


def test_search_site_all_still_asks_both_auctions():
    payload = provider_params(AuctionApiClient.GET_CURRENT_LOTS, CurrentSearchParams(site="all"))
    assert payload["site"] == [1, 2]


def test_overlong_identifier_makes_no_call(fake_redis):
    api = RecordingApi(handler=None)

    async def run():
        await get_lot_vin_or_lot_id(api, "1", "A" * 65)

    with pytest.raises(BadRequestProblem):
        asyncio.run(run())
    assert api.calls == []


def test_empty_web_list_is_cached_not_found(fake_redis):
    async def handler(schema, data):
        return AuctionApiClient().process_response([], schema)

    api = RecordingApi(handler)

    async def run():
        with pytest.raises(NotFoundProblem):
            await get_lot_vin_or_lot_id(api, "1", "21")
        with pytest.raises(NotFoundProblem):
            await get_lot_vin_or_lot_id(api, "1", "21")

    asyncio.run(run())
    assert _endpoints(api) == ["cars/lot-id/web"]


def _session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(SavedLots.__table__.create)

    asyncio.run(prepare())
    return engine, maker


def test_vin_rows_put_the_active_lot_first():
    engine, maker = _session_factory()

    async def seed_and_read():
        async with maker() as session:
            session.add(SavedLots(lot_id="1", site=1, vin="SHARED", is_deleted=True))
            session.add(SavedLots(lot_id="9", site=1, vin="SHARED", is_deleted=False))
            await session.commit()
        async with maker() as session:
            rows = await find_saved_lots_by_vin(session, "shared")
            return [(row.lot_id, row.is_deleted) for row in rows]

    try:
        assert asyncio.run(seed_and_read()) == [("9", False), ("1", True)]
    finally:
        asyncio.run(engine.dispose())


def test_grpc_site_all_catalog_miss_calls_web(fake_redis, monkeypatch):
    engine, maker = _session_factory()
    monkeypatch.setattr("rpc_server.lot_rpc.settings.REDIS_URL", "")
    monkeypatch.setattr("rpc_server.lot_rpc.AsyncSessionLocal", maker)

    async def handler(schema, data):
        return BasicLot(lot_id=21, site=1, vin="WEB", form_get_type="active")

    api = RecordingApi(handler)
    rpc = LotRpc()
    rpc.api = api
    context = _Context()
    request = lot_pb2.GetLotRequest(lot_id=21, site="3")

    async def run():
        return await rpc.GetLot(request, context)

    try:
        response = asyncio.run(run())
    finally:
        asyncio.run(engine.dispose())

    assert context.code is None
    assert len(response.lot) == 1
    assert _endpoints(api) == ["cars/lot-id/web"]


def test_grpc_catalog_miss_does_not_call_sale_history(fake_redis, monkeypatch):
    engine, maker = _session_factory()
    monkeypatch.setattr("rpc_server.lot_rpc.settings.REDIS_URL", "")
    monkeypatch.setattr("rpc_server.lot_rpc.AsyncSessionLocal", maker)

    async def handler(schema, data):
        return BasicHistoryLot(lot_id=21, site=1, vin="HIST", sale_count=3)

    api = RecordingApi(handler)
    rpc = LotRpc()
    rpc.api = api
    context = _Context()
    request = lot_pb2.GetLotRequest(lot_id=21, site="1")

    async def run():
        first = await rpc.GetLot(request, context)
        second = await rpc.GetLot(request, context)
        async with maker() as session:
            from sqlalchemy import select

            rows = (await session.execute(select(SavedLots))).scalars().all()
        return first, second, rows

    first, second, rows = asyncio.run(run())
    asyncio.run(engine.dispose())

    assert context.code is None
    assert len(first.lot) == 1
    assert len(second.lot) == 1
    assert _endpoints(api) == ["cars/lot-id/web"]
    assert rows == []


def test_grpc_deleted_feed_row_fetches_sale_history_once(fake_redis, monkeypatch):
    engine, maker = _session_factory()
    monkeypatch.setattr("rpc_server.lot_rpc.settings.REDIS_URL", "")
    monkeypatch.setattr("rpc_server.lot_rpc.AsyncSessionLocal", maker)

    async def seed():
        async with maker() as session:
            session.add(
                SavedLots(
                    lot_id="21",
                    site=1,
                    vin="FEED",
                    is_deleted=True,
                    deleted_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

    asyncio.run(seed())

    async def handler(schema, data):
        return BasicHistoryLot(
            lot_id=21,
            site=1,
            vin="FEED",
            sale_status="Sold",
            purchase_price=10,
        )

    api = RecordingApi(handler)
    rpc = LotRpc()
    rpc.api = api
    context = _Context()
    request = lot_pb2.GetLotRequest(lot_id=21, site="1")

    async def run():
        await rpc.GetLot(request, context)
        await rpc.GetLot(request, context)

    asyncio.run(run())
    asyncio.run(engine.dispose())

    assert context.code is None
    assert _endpoints(api) == ["sale-histories/lot-id"]
