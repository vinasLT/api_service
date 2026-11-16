from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobs.job_runs as job_runs
from database.models.job_runs import JobRun
from jobs.scheduler import (
    _job_locks,
    _lock_for,
    build_scheduler,
    dispatch_manual_runs,
    run_job,
)
from tests.test_job_runs import FakeProcess

VILNIUS = ZoneInfo("Europe/Vilnius")


def _next_fire(job, now: datetime) -> datetime:
    return job.trigger.get_next_fire_time(None, now)


def test_scheduler_registers_all_jobs_without_overlap():
    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {
        "lots_bootstrap",
        "lots_full_verify",
        "lots_sync",
        "sitemap",
        "manual_dispatcher",
    }
    dispatcher = jobs["manual_dispatcher"]
    assert dispatcher.max_instances == 1
    assert dispatcher.coalesce is True
    assert jobs["lots_bootstrap"].args[1:3] == ("jobs.lots_full_load", ["--mode", "bootstrap"])
    assert jobs["lots_full_verify"].args[1:3] == ("jobs.lots_full_load", ["--mode", "verify"])
    assert jobs["lots_sync"].args[1] == "jobs.lots_sync"
    assert jobs["sitemap"].args[1] == "jobs.sitemap_generator"
    for job in jobs.values():
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.misfire_grace_time == 600


def test_weekly_verify_runs_sunday_3am_vilnius():
    job = build_scheduler().get_job("lots_full_verify")

    # Friday afternoon, winter time (UTC+2), then summer time (UTC+3).
    winter = _next_fire(job, datetime(2026, 11, 6, 16, 0, tzinfo=VILNIUS))
    summer = _next_fire(job, datetime(2026, 7, 1, 12, 0, tzinfo=VILNIUS))

    assert winter == datetime(2026, 11, 8, 3, 0, tzinfo=VILNIUS)
    assert winter.utcoffset().total_seconds() == 2 * 3600
    assert summer == datetime(2026, 7, 5, 3, 0, tzinfo=VILNIUS)
    assert summer.utcoffset().total_seconds() == 3 * 3600


def test_sync_hourly_and_sitemap_every_three_hours():
    scheduler = build_scheduler()
    now = datetime(2026, 11, 6, 16, 10, tzinfo=VILNIUS)

    sync = scheduler.get_job("lots_sync")
    first_sync = _next_fire(sync, now)
    assert first_sync == datetime(2026, 11, 6, 17, 5, tzinfo=VILNIUS)
    assert _next_fire(sync, first_sync.replace(minute=6)) == datetime(
        2026, 11, 6, 18, 5, tzinfo=VILNIUS
    )

    sitemap = scheduler.get_job("sitemap")
    assert _next_fire(sitemap, now) == datetime(2026, 11, 6, 18, 30, tzinfo=VILNIUS)
    assert _next_fire(sitemap, datetime(2026, 11, 6, 18, 31, tzinfo=VILNIUS)) == datetime(
        2026, 11, 6, 21, 30, tzinfo=VILNIUS
    )


@pytest.fixture
def engine(monkeypatch):
    bind = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    JobRun.__table__.create(bind)
    monkeypatch.setattr(job_runs, "db_engine", bind)
    _job_locks.clear()
    return bind


def _row(engine) -> JobRun:
    with Session(engine) as session:
        row = session.scalar(select(JobRun))
        session.expunge_all()
        return row


def test_dispatcher_claims_queued_run(engine, monkeypatch):
    process = FakeProcess()

    def popen(command, env):
        process.env = env
        return process

    monkeypatch.setattr("jobs.scheduler.subprocess.Popen", popen)
    run_id = job_runs.queue_run("sitemap", "admin@example.com")
    started: list[int] = []

    def submit(job_id, module, args, timeout, claimed_id):
        started.append(claimed_id)
        run_job(job_id, module, args, timeout, claimed_id)

    dispatch_manual_runs(submit=submit)

    assert started == [run_id]
    row = _row(engine)
    assert row.status == job_runs.STATUS_SUCCEEDED
    assert row.trigger == job_runs.TRIGGER_MANUAL
    assert row.requested_by == "admin@example.com"
    assert process.env[job_runs.JOB_RUN_ID_ENV] == str(run_id)


def test_busy_lock_leaves_manual_run_queued(engine):
    job_runs.queue_run("sitemap", "admin@example.com")
    lock = _lock_for("sitemap")
    assert lock.acquire(blocking=False)
    try:
        dispatch_manual_runs(submit=lambda *_args: pytest.fail("job should stay queued"))
    finally:
        lock.release()

    assert _row(engine).status == job_runs.STATUS_QUEUED


def test_scheduled_run_skips_while_lock_is_held(engine):
    lock = _lock_for("lots_sync")
    assert lock.acquire(blocking=False)
    try:
        run_job("lots_sync", "jobs.lots_sync", [], 10)
    finally:
        lock.release()

    row = _row(engine)
    assert row.status == job_runs.STATUS_SKIPPED
    assert row.result == {"skipped": "already_running"}
    assert row.trigger == job_runs.TRIGGER_SCHEDULED


def test_dispatcher_fails_unknown_job(engine):
    job_runs.queue_run("retired-job", None)

    dispatch_manual_runs()

    row = _row(engine)
    assert row.status == job_runs.STATUS_FAILED
    assert row.error == "Unknown job"
