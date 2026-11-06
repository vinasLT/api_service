import asyncio
from contextlib import asynccontextmanager

import pytest

import jobs.lots_full_load as full_load
from jobs.lots_full_load import FullLoadMode


@pytest.fixture(autouse=True)
def lock_always_free(monkeypatch):
    @asynccontextmanager
    async def free_lock(engine, name):
        yield True

    monkeypatch.setattr(full_load, "advisory_lock", free_lock)


async def _fail_load(replace: bool):
    raise AssertionError("full load must not run")


def test_bootstrap_skips_when_table_has_rows(monkeypatch):
    async def populated():
        return True

    monkeypatch.setattr(full_load, "has_saved_lots", populated)
    monkeypatch.setattr(full_load, "_load", _fail_load)

    result = asyncio.run(full_load.run(FullLoadMode.BOOTSTRAP))

    assert result == {"mode": "bootstrap", "skipped": "already_populated"}


def _patch_counts(monkeypatch, counts: list[int]):
    async def count():
        return counts.pop(0)

    monkeypatch.setattr(full_load, "count_active_lots", count)


def test_bootstrap_loads_with_replace_when_empty(monkeypatch):
    calls = []

    async def empty():
        return False

    async def load(replace: bool):
        calls.append(replace)
        return 2, 100, 100

    monkeypatch.setattr(full_load, "has_saved_lots", empty)
    monkeypatch.setattr(full_load, "_load", load)
    _patch_counts(monkeypatch, [0, 100])

    result = asyncio.run(full_load.run(FullLoadMode.BOOTSTRAP))

    assert calls == [True]
    assert result["added_count"] == 100
    assert result["within_threshold"] is True


def test_verify_never_replaces_and_reports_gap(monkeypatch):
    calls = []

    async def load(replace: bool):
        calls.append(replace)
        return 1, 1000, 30

    monkeypatch.setattr(full_load, "_load", load)
    _patch_counts(monkeypatch, [880, 900])

    result = asyncio.run(full_load.run(FullLoadMode.VERIFY))

    assert calls == [False]
    assert result["added_count"] == 20
    assert result["feed_vs_db_diff_percent"] == 10.0
    assert result["within_threshold"] is False
