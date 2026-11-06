from datetime import datetime
from zoneinfo import ZoneInfo

from jobs.scheduler import build_scheduler

VILNIUS = ZoneInfo("Europe/Vilnius")


def _next_fire(job, now: datetime) -> datetime:
    return job.trigger.get_next_fire_time(None, now)


def test_scheduler_registers_all_jobs_without_overlap():
    scheduler = build_scheduler()
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {"lots_bootstrap", "lots_full_verify", "lots_sync", "sitemap"}
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
