from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud.base import BaseService
from database.models.job_runs import JobRun
from request_schemas.job_runs import JobRunsFilterIn


class JobRunsService(BaseService[JobRun, BaseModel, BaseModel]):
    def __init__(self, session: AsyncSession):
        super().__init__(JobRun, session)

    async def list_runs(self, filters: JobRunsFilterIn) -> tuple[int, list[JobRun]]:
        clauses = self._clauses(filters)
        total = await self.session.scalar(
            select(func.count()).select_from(JobRun).where(*clauses)
        )
        rows = await self.session.scalars(
            select(JobRun)
            .where(*clauses)
            .order_by(JobRun.started_at.desc(), JobRun.id.desc())
            .limit(filters.limit)
            .offset(filters.offset)
        )
        return total or 0, list(rows)

    async def job_ids(self) -> list[str]:
        rows = await self.session.scalars(select(JobRun.job_id).distinct())
        return list(rows)

    async def latest(self, job_id: str) -> JobRun | None:
        return await self._latest(job_id)

    async def latest_runs(self, job_id: str, limit: int) -> list[JobRun]:
        rows = await self.session.scalars(
            select(JobRun)
            .where(JobRun.job_id == job_id)
            .order_by(JobRun.started_at.desc(), JobRun.id.desc())
            .limit(limit)
        )
        return list(rows)

    async def last_with_status(self, job_id: str, statuses: set[str]) -> JobRun | None:
        return await self._latest(job_id, statuses)

    async def count_since(
        self, job_id: str, statuses: set[str], since: datetime | None
    ) -> int:
        statement = (
            select(func.count())
            .select_from(JobRun)
            .where(JobRun.job_id == job_id, JobRun.status.in_(statuses))
        )
        if since is not None:
            statement = statement.where(JobRun.started_at > since)
        return await self.session.scalar(statement) or 0

    async def counts_by_status(self, job_id: str, since: datetime) -> dict[str, int]:
        rows = await self.session.execute(
            select(JobRun.status, func.count())
            .where(JobRun.job_id == job_id, JobRun.started_at >= since)
            .group_by(JobRun.status)
        )
        return {status: count for status, count in rows.all()}

    async def _latest(self, job_id: str, statuses: set[str] | None = None) -> JobRun | None:
        statement = select(JobRun).where(JobRun.job_id == job_id)
        if statuses is not None:
            statement = statement.where(JobRun.status.in_(statuses))
        statement = statement.order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(1)
        return await self.session.scalar(statement)

    @staticmethod
    def _clauses(filters: JobRunsFilterIn) -> list:
        clauses = []
        if filters.job_id:
            clauses.append(JobRun.job_id == filters.job_id)
        if filters.status:
            clauses.append(JobRun.status.in_(filters.status))
        if filters.trigger:
            clauses.append(JobRun.trigger == filters.trigger)
        if filters.started_from:
            clauses.append(JobRun.started_at >= filters.started_from)
        if filters.started_to:
            clauses.append(JobRun.started_at <= filters.started_to)
        return clauses
