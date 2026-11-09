import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database.db.session import get_async_db
from database.models.job_runs import JobRun
from main import app

FROZEN = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
TRACEBACK = "Traceback (most recent call last):\n  File \"job.py\", line 1, in <module>\nRuntimeError: feed down"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("services.job_status._now", lambda: FROZEN)
    pending: list[dict] = []
    state: dict = {}

    async def override_db():
        if "maker" not in state:
            engine = create_async_engine(
                "sqlite+aiosqlite://",
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
            async with engine.begin() as connection:
                await connection.run_sync(JobRun.__table__.create)
            state["engine"] = engine
            state["maker"] = async_sessionmaker(
                engine, expire_on_commit=False, class_=AsyncSession
            )
        async with state["maker"]() as session:
            while pending:
                session.add(JobRun(**pending.pop(0)))
            await session.commit()
            yield session

    app.dependency_overrides[get_async_db] = override_db
    with TestClient(app) as test_client:
        yield test_client, pending
    app.dependency_overrides.pop(get_async_db, None)
    engine = state.get("engine")
    if engine is not None:
        asyncio.run(engine.dispose())


def _run(job_id: str, status: str, started: datetime, **extra) -> dict:
    return {
        "job_id": job_id,
        "trigger": extra.pop("trigger", "scheduled"),
        "status": status,
        "started_at": started,
        "finished_at": extra.pop("finished_at", started),
        "duration_seconds": extra.pop("duration_seconds", 1.0),
        "exit_code": extra.pop("exit_code", 0 if status in {"succeeded", "skipped"} else 1),
        **extra,
    }


def _seed(pending: list[dict]) -> None:
    pending.extend(
        [
            _run(
                "lots_sync",
                "failed",
                datetime(2026, 11, 7, 8, 5, tzinfo=timezone.utc),
                error="old failure",
            ),
            _run(
                "lots_sync",
                "succeeded",
                datetime(2026, 11, 9, 6, 0, tzinfo=timezone.utc),
                result={"lots": 10},
            ),
            _run(
                "lots_sync",
                "failed",
                datetime(2026, 11, 9, 7, 5, tzinfo=timezone.utc),
                error=TRACEBACK,
            ),
            _run(
                "lots_sync",
                "failed",
                datetime(2026, 11, 9, 8, 5, tzinfo=timezone.utc),
                error=TRACEBACK,
            ),
            _run(
                "sitemap",
                "skipped",
                datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc),
                result={"skipped": "not_bootstrapped"},
                exit_code=0,
            ),
            _run(
                "lots_full_verify",
                "succeeded",
                datetime(2026, 11, 9, 9, 30, tzinfo=timezone.utc),
            ),
            _run(
                "lots_full_verify",
                "running",
                datetime(2026, 11, 9, 9, 50, tzinfo=timezone.utc),
                finished_at=None,
                exit_code=None,
                duration_seconds=None,
            ),
            _run(
                "lots_full_load[bootstrap]",
                "succeeded",
                datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc),
                trigger="manual",
            ),
        ]
    )


def test_job_summaries_report_health_failures_and_overdue(client):
    test_client, pending = client
    _seed(pending)

    response = test_client.get("/admin/v1/jobs")
    assert response.status_code == 200
    jobs = {item["job_id"]: item for item in response.json()}

    assert set(jobs) == {
        "lots_bootstrap",
        "lots_full_verify",
        "lots_sync",
        "sitemap",
        "lots_full_load[bootstrap]",
    }

    sync = jobs["lots_sync"]
    assert sync["scheduled"] is True
    assert sync["schedule"] == "5 * * * *"
    assert sync["healthy"] is False
    assert sync["overdue"] is True
    assert sync["running"] is False
    assert sync["consecutive_failures"] == 2
    assert sync["last_run"]["status"] == "failed"
    assert sync["last_success_at"].startswith("2026-11-09T06:00")
    assert sync["last_failure_at"].startswith("2026-11-09T08:05")
    assert sync["last_24h"] == {
        "running": 0,
        "succeeded": 1,
        "skipped": 0,
        "failed": 2,
        "timeout": 0,
        "interrupted": 0,
    }
    assert sync["next_run_at"] is not None

    sitemap = jobs["sitemap"]
    assert sitemap["healthy"] is True
    assert sitemap["overdue"] is False
    assert sitemap["consecutive_failures"] == 0
    assert sitemap["schedule"] == "30 */3 * * *"

    verify = jobs["lots_full_verify"]
    assert verify["running"] is True
    assert verify["healthy"] is True
    assert verify["overdue"] is False
    assert verify["consecutive_failures"] == 0
    assert verify["last_run"]["status"] == "running"

    bootstrap = jobs["lots_bootstrap"]
    assert bootstrap["schedule"] == "on startup"
    assert bootstrap["next_run_at"] is None
    assert bootstrap["overdue"] is False
    assert bootstrap["healthy"] is False

    manual = jobs["lots_full_load[bootstrap]"]
    assert manual["scheduled"] is False
    assert manual["schedule"] is None
    assert manual["timeout_seconds"] is None
    assert manual["healthy"] is True
    assert manual["overdue"] is False


def test_job_detail_includes_recent_runs(client):
    test_client, pending = client
    _seed(pending)

    response = test_client.get("/admin/v1/jobs/lots_sync")
    assert response.status_code == 200
    body = response.json()
    assert body["consecutive_failures"] == 2
    assert [run["status"] for run in body["runs"]] == ["failed", "failed", "succeeded", "failed"]
    assert body["runs"][0]["error_summary"] == "RuntimeError: feed down"
    assert "error" not in body["runs"][0]
    assert "Traceback" not in body["runs"][0]["error_summary"]


def test_run_history_filters_and_paginates(client):
    test_client, pending = client
    _seed(pending)

    response = test_client.get(
        "/admin/v1/jobs/runs",
        params={"job_id": "lots_sync", "status": "failed", "limit": 1, "offset": 0},
    )
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    assert len(page["items"]) == 1
    assert page["items"][0]["started_at"].startswith("2026-11-09T08:05")
    assert page["items"][0]["error_summary"] == "RuntimeError: feed down"

    older = test_client.get(
        "/admin/v1/jobs/runs",
        params=[
            ("job_id", "lots_sync"),
            ("status", "failed"),
            ("status", "succeeded"),
            ("limit", "1"),
            ("offset", "1"),
        ],
    )
    assert older.status_code == 200
    body = older.json()
    assert body["total"] == 4
    assert body["items"][0]["started_at"].startswith("2026-11-09T07:05")

    manual = test_client.get("/admin/v1/jobs/runs", params={"trigger": "manual"})
    assert manual.status_code == 200
    assert manual.json()["total"] == 1
    assert manual.json()["items"][0]["job_id"] == "lots_full_load[bootstrap]"


def test_run_detail_includes_traceback_and_result(client):
    test_client, pending = client
    _seed(pending)

    listing = test_client.get("/admin/v1/jobs/runs", params={"job_id": "sitemap"})
    run_id = listing.json()["items"][0]["id"]

    detail = test_client.get(f"/admin/v1/jobs/runs/{run_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["result"] == {"skipped": "not_bootstrapped"}
    assert body["error"] is None

    failed = test_client.get(
        "/admin/v1/jobs/runs", params={"job_id": "lots_sync", "status": "failed", "limit": 1}
    )
    failed_detail = test_client.get(f"/admin/v1/jobs/runs/{failed.json()['items'][0]['id']}")
    assert failed_detail.status_code == 200
    assert failed_detail.json()["error"] == TRACEBACK


def test_unknown_job_and_run_are_not_found(client):
    test_client, _pending = client

    assert test_client.get("/admin/v1/jobs/runs/999").status_code == 404
    assert test_client.get("/admin/v1/jobs/does-not-exist").status_code == 404
