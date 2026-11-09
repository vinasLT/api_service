import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import jobs.job_runs as job_runs
from database.models.job_runs import JobRun
from jobs import common
from jobs.scheduler import run_job


@pytest.fixture
def engine(monkeypatch):
    bind = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    JobRun.__table__.create(bind)
    monkeypatch.setattr(job_runs, "db_engine", bind)
    return bind


@pytest.fixture(autouse=True)
def no_job_run_env(monkeypatch):
    monkeypatch.delenv(job_runs.JOB_RUN_ID_ENV, raising=False)


@pytest.fixture
def no_dispose(monkeypatch):
    class DummyEngine:
        async def dispose(self):
            return None

    monkeypatch.setattr(common, "engine_async", DummyEngine())


def _rows(engine) -> list[JobRun]:
    with Session(engine) as session:
        rows = list(session.scalars(select(JobRun).order_by(JobRun.id)))
        session.expunge_all()
        return rows


def _shift_started_at(engine, run_id: int, started_at: datetime) -> None:
    with Session(engine) as session:
        session.execute(
            update(JobRun).where(JobRun.id == run_id).values(started_at=started_at)
        )
        session.commit()


class FakeProcess:
    def __init__(self, returncode: int = 0, hang: bool = False, on_wait=None):
        self.returncode = None
        self._code = returncode
        self.hang = hang
        self.on_wait = on_wait
        self.env = None

    def wait(self, timeout=None):
        if self.on_wait is not None:
            self.on_wait(self)
            self.on_wait = None
        if self.hang and self.returncode is None:
            raise subprocess.TimeoutExpired("job", timeout or 0)
        self.returncode = self._code
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = self._code

    def kill(self):
        self.returncode = self._code


def test_success_skipped_failure_and_timeout(engine):
    succeeded = job_runs.start_run("lots_sync", job_runs.TRIGGER_SCHEDULED)
    job_runs.record_outcome(succeeded, result={"lots": 3})
    job_runs.finish_run(succeeded, exit_code=0, timed_out=False, duration=1.5)

    skipped = job_runs.start_run("sitemap", job_runs.TRIGGER_SCHEDULED)
    job_runs.record_outcome(skipped, result={"skipped": "not_bootstrapped"})
    job_runs.finish_run(skipped, exit_code=0, timed_out=False, duration=0.2)

    failed = job_runs.start_run("lots_sync", job_runs.TRIGGER_SCHEDULED)
    job_runs.record_outcome(failed, error="RuntimeError: boom")
    job_runs.finish_run(failed, exit_code=1, timed_out=False, duration=4)

    timed_out = job_runs.start_run("lots_bootstrap", job_runs.TRIGGER_SCHEDULED)
    job_runs.record_outcome(timed_out, result={"lots": 1})
    job_runs.finish_run(timed_out, exit_code=None, timed_out=True, duration=60)

    rows = {row.id: row for row in _rows(engine)}
    assert rows[succeeded].status == job_runs.STATUS_SUCCEEDED
    assert rows[succeeded].result == {"lots": 3}
    assert rows[succeeded].exit_code == 0
    assert rows[succeeded].duration_seconds == 1.5
    assert rows[succeeded].finished_at is not None

    assert rows[skipped].status == job_runs.STATUS_SKIPPED
    assert rows[skipped].result == {"skipped": "not_bootstrapped"}

    assert rows[failed].status == job_runs.STATUS_FAILED
    assert rows[failed].error == "RuntimeError: boom"
    assert rows[failed].exit_code == 1

    assert rows[timed_out].status == job_runs.STATUS_TIMEOUT
    assert rows[timed_out].result == {"lots": 1}
    assert rows[timed_out].finished_at is not None


def test_mark_interrupted_only_changes_running_rows(engine):
    running = job_runs.start_run("lots_sync", job_runs.TRIGGER_SCHEDULED)
    done = job_runs.start_run("sitemap", job_runs.TRIGGER_SCHEDULED)
    job_runs.finish_run(done, exit_code=0, timed_out=False, duration=1)

    assert job_runs.mark_interrupted() == 1

    rows = {row.id: row for row in _rows(engine)}
    assert rows[running].status == job_runs.STATUS_INTERRUPTED
    assert rows[running].finished_at is not None
    assert rows[done].status == job_runs.STATUS_SUCCEEDED


def test_prune_deletes_rows_older_than_retention(engine):
    old = job_runs.start_run("lots_sync", job_runs.TRIGGER_SCHEDULED)
    recent = job_runs.start_run("lots_sync", job_runs.TRIGGER_SCHEDULED)
    _shift_started_at(engine, old, datetime.now(timezone.utc) - timedelta(days=31))

    assert job_runs.prune(30) == 1
    assert [row.id for row in _rows(engine)] == [recent]


def test_recording_failure_does_not_raise(engine, monkeypatch):
    broken = create_engine("sqlite://")
    monkeypatch.setattr(job_runs, "db_engine", broken)

    assert job_runs.start_run("lots_sync", job_runs.TRIGGER_MANUAL) is None
    job_runs.record_outcome(1, result={"lots": 1})
    job_runs.finish_run(1, exit_code=0, timed_out=False, duration=1)
    assert job_runs.mark_interrupted() is None
    assert job_runs.prune(30) is None


def test_scheduler_records_scheduled_run(engine, monkeypatch):
    process = FakeProcess(
        on_wait=lambda proc: job_runs.record_outcome(
            int(proc.env[job_runs.JOB_RUN_ID_ENV]), result={"skipped": "lock_held"}
        )
    )

    def popen(command, env):
        process.env = env
        return process

    monkeypatch.setattr("jobs.scheduler.subprocess.Popen", popen)

    run_job("lots_sync", "jobs.lots_sync", [], timeout_seconds=10)

    row = _rows(engine)[0]
    assert row.job_id == "lots_sync"
    assert row.trigger == job_runs.TRIGGER_SCHEDULED
    assert row.status == job_runs.STATUS_SKIPPED
    assert row.exit_code == 0
    assert process.env[job_runs.JOB_RUN_ID_ENV] == str(row.id)


def test_scheduler_records_timeout(engine, monkeypatch):
    process = FakeProcess(hang=True, returncode=-15)

    def popen(command, env):
        process.env = env
        return process

    monkeypatch.setattr("jobs.scheduler.subprocess.Popen", popen)

    run_job("sitemap", "jobs.sitemap_generator", [], timeout_seconds=1)

    row = _rows(engine)[0]
    assert row.status == job_runs.STATUS_TIMEOUT
    assert row.exit_code == -15
    assert process.env[job_runs.JOB_RUN_ID_ENV] == str(row.id)


def test_manual_run_records_its_own_row(engine, no_dispose):
    async def job():
        return {"lots": 2}

    with pytest.raises(SystemExit) as exc:
        common.run_job("lots_full_load[bootstrap]", job)

    assert exc.value.code == 0
    row = _rows(engine)[0]
    assert row.job_id == "lots_full_load[bootstrap]"
    assert row.trigger == job_runs.TRIGGER_MANUAL
    assert row.status == job_runs.STATUS_SUCCEEDED
    assert row.result == {"lots": 2}
    assert row.exit_code == 0
    assert row.finished_at is not None


def test_manual_run_records_failure(engine, no_dispose):
    async def job():
        raise RuntimeError("feed down")

    with pytest.raises(SystemExit) as exc:
        common.run_job("lots_sync", job)

    assert exc.value.code == 1
    row = _rows(engine)[0]
    assert row.status == job_runs.STATUS_FAILED
    assert "RuntimeError: feed down" in row.error
    assert row.exit_code == 1
    assert row.finished_at is not None


def test_scheduled_child_does_not_finish_the_row(engine, no_dispose, monkeypatch):
    run_id = job_runs.start_run("lots_sync", job_runs.TRIGGER_SCHEDULED)
    monkeypatch.setenv(job_runs.JOB_RUN_ID_ENV, str(run_id))

    async def job():
        return {"lots": 9}

    with pytest.raises(SystemExit) as exc:
        common.run_job("lots_sync", job)

    assert exc.value.code == 0
    row = _rows(engine)[0]
    assert row.trigger == job_runs.TRIGGER_SCHEDULED
    assert row.status == job_runs.STATUS_SUCCEEDED
    assert row.result == {"lots": 9}
    assert row.finished_at is None
    assert row.exit_code is None


def test_manual_run_still_exits_when_recording_fails(no_dispose, monkeypatch):
    monkeypatch.setattr(job_runs, "db_engine", create_engine("sqlite://"))

    async def job():
        return {"lots": 1}

    with pytest.raises(SystemExit) as exc:
        common.run_job("lots_sync", job)

    assert exc.value.code == 0
