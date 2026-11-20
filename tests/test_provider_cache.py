import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from rfc9457 import NotFoundProblem
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from auction_api.api import AuctionApiClient
from auction_api.types.lot import BasicHistoryLot, SaleHistoryItem
from auction_api.types.search import BasicManyHistoryLot
from database.db.session import get_async_db
from database.models.saved_lots import SavedLots
from dependencies.auction_api_service import get_auction_api_service
from main import app
from request_schemas.lot import LotByIDIn
from services.http_cache import query_key_builder
from services.provider_cache import cached_provider_call, sale_history_ttl
from services.provider_usage import is_crawler, read_provider_usage, record_provider_call
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

    async def incr(self, key):
        current = int(self.store.get(key, b"0"))
        current += 1
        self.store[key] = str(current).encode()
        return current

    async def expire(self, key, ttl):
        return True

    def pipeline(self):
        return _FakePipe(self)

    async def scan_iter(self, match=None, count=None):
        from fnmatch import fnmatch

        for key in list(self.store):
            if match is None or fnmatch(key, match):
                yield key

    async def aclose(self):
        return None


class _FakePipe:
    def __init__(self, redis: FakeRedis):
        self.redis = redis
        self.ops = []

    def incr(self, key):
        self.ops.append(("incr", key))
        return self

    def expire(self, key, ttl):
        self.ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        results = []
        for op in self.ops:
            if op[0] == "incr":
                results.append(await self.redis.incr(op[1]))
            else:
                results.append(True)
        return results


class _Request:
    def __init__(self, path, query):
        self.url = type("URL", (), {"path": path})()
        self.query_params = type("Query", (), {"multi_items": lambda self: query})()


@pytest.fixture
def fake_redis(monkeypatch):
    fake = FakeRedis()

    async def init():
        set_redis(fake)
        return fake

    monkeypatch.setattr("services.redis_client.init_redis", init)
    set_redis(fake)
    yield fake
    set_redis(None)


def _history(lot_id=9, price=50):
    return BasicHistoryLot(
        lot_id=lot_id,
        site=1,
        purchase_price=price,
        sale_status="Sold",
        sale_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        sale_history=[
            SaleHistoryItem(
                lot_id=lot_id,
                site=1,
                vin="1HGCM82633A004352",
                sale_status="Sold",
                purchase_price=price,
            )
        ],
    )


def test_query_key_ignores_request_objects():
    request = _Request("/public/v1/lot/current", [("site", "1"), ("make", "Ford")])
    first = query_key_builder(get_async_db, "ns", request=request, args=(), kwargs={"api": object()})
    second = query_key_builder(get_async_db, "ns", request=request, args=(), kwargs={"db": object()})
    other = query_key_builder(
        get_async_db,
        "ns",
        request=_Request("/public/v1/lot/current", [("make", "Ford"), ("site", "2")]),
        args=(),
        kwargs={},
    )

    assert first == second
    assert first != other


def test_identical_provider_calls_are_cached(fake_redis):
    calls = 0

    class Api:
        async def request_with_schema(self, schema, data, **kwargs):
            nonlocal calls
            calls += 1
            return _history()

    data = LotByIDIn(lot_id=9, site="1")

    async def run():
        first = await cached_provider_call(
            Api(), AuctionApiClient.GET_LOT_HISTORY_BY_ID, data, ttl=sale_history_ttl
        )
        second = await cached_provider_call(
            Api(), AuctionApiClient.GET_LOT_HISTORY_BY_ID, data, ttl=sale_history_ttl
        )
        return first, second

    first, second = asyncio.run(run())
    assert calls == 1
    assert first.purchase_price == second.purchase_price == 50


def test_not_found_is_cached(fake_redis):
    calls = 0

    class Api:
        async def request_with_schema(self, schema, data, **kwargs):
            nonlocal calls
            calls += 1
            raise NotFoundProblem("Lot not found")

    data = LotByIDIn(lot_id=9, site="1")

    async def run():
        with pytest.raises(NotFoundProblem):
            await cached_provider_call(
                Api(), AuctionApiClient.GET_LOT_HISTORY_BY_ID, data, ttl=sale_history_ttl
            )
        with pytest.raises(NotFoundProblem):
            await cached_provider_call(
                Api(), AuctionApiClient.GET_LOT_HISTORY_BY_ID, data, ttl=sale_history_ttl
            )

    asyncio.run(run())
    assert calls == 1


def test_concurrent_callers_share_one_provider_request(fake_redis):
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    class Api:
        async def request_with_schema(self, schema, data, **kwargs):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return _history()

    data = LotByIDIn(lot_id=9, site="1")

    async def run():
        first = asyncio.create_task(
            cached_provider_call(
                Api(), AuctionApiClient.GET_LOT_HISTORY_BY_ID, data, ttl=sale_history_ttl
            )
        )
        await started.wait()
        second = asyncio.create_task(
            cached_provider_call(
                Api(), AuctionApiClient.GET_LOT_HISTORY_BY_ID, data, ttl=sale_history_ttl
            )
        )
        await asyncio.sleep(0.05)
        release.set()
        return await first, await second

    first, second = asyncio.run(run())
    assert calls == 1
    assert second.purchase_price == first.purchase_price


def test_provider_usage_counts_bot_calls(fake_redis):
    async def run():
        token = is_crawler.set(True)
        try:
            await record_provider_call("history-cars")
        finally:
            is_crawler.reset(token)
        await record_provider_call("history-cars")
        return await read_provider_usage()

    usage = asyncio.run(run())
    history = next(item for item in usage["endpoints"] if item["endpoint"] == "history-cars")
    assert history["calls"] == 2
    assert history["bot_calls"] == 1


@pytest.fixture
def client(fake_redis):
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(SavedLots.__table__.create)

    asyncio.run(prepare())
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    calls: list[str] = []

    async def override_db():
        async with maker() as session:
            yield session

    class Stub(AuctionApiClient):
        async def request_with_schema(self, schema, data, **kwargs):
            calls.append(schema.endpoint.value)
            if schema.is_pagination:
                return BasicManyHistoryLot(
                    size=10,
                    page=1,
                    pages=1,
                    count=1,
                    data=[_history(price=80)],
                )
            return _history(lot_id=getattr(data, "lot_id", 9))

    app.dependency_overrides[get_async_db] = override_db
    app.dependency_overrides[get_auction_api_service] = lambda: Stub()
    with TestClient(app) as test_client:
        yield test_client, calls, maker
    app.dependency_overrides.pop(get_async_db, None)
    app.dependency_overrides.pop(get_auction_api_service, None)
    asyncio.run(engine.dispose())


def test_sales_history_and_history_lot_share_one_call(client):
    test_client, calls, _maker = client
    by_id = test_client.get("/public/v1/lot/history/lot-id", params={"lot_id": 9, "site": 1})
    sales = test_client.get("/public/v1/lot/sales-history", params={"lot_id": 9, "site": 1})

    assert by_id.status_code == 200
    assert sales.status_code == 200
    assert calls == ["sale-histories/lot-id"]
    assert sales.json()[0]["final_bid"] == 50


def test_similar_sales_and_prices_share_one_call(client):
    test_client, calls, _maker = client
    params = {"site": 1, "make": "Ford", "model": "F150", "year": 2018}
    listing = test_client.get("/public/v1/lot/similar-sales", params=params)
    prices = test_client.get("/public/v1/lot/similar-sales/prices", params=params)

    assert listing.status_code == 200
    assert prices.status_code == 200
    assert prices.json()["min_price"] == 80
    assert calls == ["history-cars"]


def test_saved_sold_lot_fetches_sale_history_once(client):
    test_client, calls, maker = client

    async def insert():
        async with maker() as session:
            session.add(
                SavedLots(
                    lot_id="42",
                    site=1,
                    base_site="copart",
                    vin="1HGCM82633A004352",
                    year=2003,
                    make="Honda",
                    model="Accord",
                    is_deleted=True,
                )
            )
            await session.commit()

    asyncio.run(insert())
    first = test_client.get("/public/v1/lot/saved", params={"lot_id": 42, "site": "copart"})
    second = test_client.get("/public/v1/lot/saved", params={"lot_id": 42, "site": "copart"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["form_get_type"] == "history"
    assert first.json()["purchase_price"] == 50
    assert calls == ["sale-histories/lot-id"]


def test_saved_active_lot_does_not_call_the_provider(client):
    test_client, calls, maker = client

    async def insert():
        async with maker() as session:
            session.add(
                SavedLots(
                    lot_id="7",
                    site=2,
                    base_site="iaai",
                    make="Ford",
                    model="Focus",
                    year=2020,
                    is_deleted=False,
                )
            )
            await session.commit()

    asyncio.run(insert())
    response = test_client.get("/public/v1/lot/saved", params={"lot_id": 7, "site": 2})

    assert response.status_code == 200
    assert response.json()["form_get_type"] == "active"
    assert calls == []


def test_missing_saved_lot_is_not_found(client):
    test_client, calls, _maker = client
    response = test_client.get("/public/v1/lot/saved", params={"lot_id": 404, "site": 1})
    assert response.status_code == 404
    assert calls == []


def test_api_robots_disallows_the_public_api():
    with TestClient(app) as test_client:
        response = test_client.get("/robots.txt")
    assert response.status_code == 200
    assert "Disallow: /auction-api/" in response.text
