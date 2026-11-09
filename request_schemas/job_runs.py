from datetime import datetime

from pydantic import BaseModel, Field


class JobRunsFilterIn(BaseModel):
    job_id: str | None = None
    status: list[str] = Field(default_factory=list)
    trigger: str | None = None
    started_from: datetime | None = None
    started_to: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class LastRunOut(BaseModel):
    id: int
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    exit_code: int | None


class StatusCountsOut(BaseModel):
    running: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    timeout: int = 0
    interrupted: int = 0


class JobRunOut(BaseModel):
    id: int
    job_id: str
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_seconds: float | None
    exit_code: int | None
    error_summary: str | None = None


class JobRunDetailOut(JobRunOut):
    result: dict | None = None
    error: str | None = None


class JobRunsPageOut(BaseModel):
    total: int
    items: list[JobRunOut]


class JobSummaryOut(BaseModel):
    job_id: str
    scheduled: bool
    enabled: bool
    schedule: str | None
    timeout_seconds: int | None
    running: bool
    healthy: bool
    overdue: bool
    consecutive_failures: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    next_run_at: datetime | None
    last_run: LastRunOut | None
    last_24h: StatusCountsOut


class JobDetailOut(JobSummaryOut):
    runs: list[JobRunOut]
