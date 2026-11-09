import logging
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

import jobs.job_runs as job_runs
from core.logger import logger

# Crontab expressions are evaluated in SCHEDULER_TIMEZONE. APScheduler numbers
# weekdays from 0=mon (not 0=sun), so use day names like "sun".
SCHEDULER_TIMEZONE = "Europe/Vilnius"
ENABLE_LOTS_BOOTSTRAP = True
ENABLE_LOTS_VERIFY = True
ENABLE_LOTS_SYNC = True
ENABLE_SITEMAP = True
LOTS_VERIFY_CRON = "0 3 * * sun"
LOTS_SYNC_CRON = "5 * * * *"
SITEMAP_CRON = "30 */3 * * *"
LOTS_FULL_LOAD_TIMEOUT_SECONDS = 6 * 60 * 60
LOTS_SYNC_TIMEOUT_SECONDS = 50 * 60
SITEMAP_TIMEOUT_SECONDS = 2 * 60 * 60
JOB_RUNS_RETENTION_DAYS = 30
MISFIRE_GRACE_SECONDS = 600
TERMINATE_GRACE_SECONDS = 30

_children: set[subprocess.Popen] = set()
_children_lock = threading.Lock()


def run_job(job_id: str, module: str, args: list[str], timeout_seconds: int) -> None:
    command = [sys.executable, "-m", module, *args]
    extra = {"job_id": job_id, "command": " ".join(command)}
    logger.info(f"Starting job {job_id}", extra=extra)
    started_at = time.perf_counter()

    run_id = job_runs.start_run(job_id, job_runs.TRIGGER_SCHEDULED)
    env = os.environ.copy()
    if run_id is not None:
        env[job_runs.JOB_RUN_ID_ENV] = str(run_id)

    process = subprocess.Popen(command, env=env)
    with _children_lock:
        _children.add(process)
    timed_out = False
    try:
        return_code = process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        logger.error(
            f"Job {job_id} exceeded {timeout_seconds}s timeout; killing it",
            extra=extra,
        )
        timed_out = True
        _stop(process)
        return_code = process.returncode
    finally:
        with _children_lock:
            _children.discard(process)

    duration = round(time.perf_counter() - started_at, 3)
    job_runs.finish_run(run_id, return_code, timed_out, duration)
    result_extra = {**extra, "return_code": return_code, "duration_seconds": duration}
    if return_code == 0:
        logger.info(f"Job {job_id} finished in {duration}s", extra=result_extra)
    else:
        logger.error(
            f"Job {job_id} failed with exit code {return_code} after {duration}s",
            extra=result_extra,
        )


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@dataclass(frozen=True)
class JobSpec:
    job_id: str
    enabled: bool
    trigger: CronTrigger | DateTrigger
    module: str
    args: list[str]
    timeout: int
    schedule: str


def scheduled_jobs(timezone: ZoneInfo) -> list[JobSpec]:
    """Job definitions shared by the scheduler and the admin status API."""
    return [
        JobSpec(
            "lots_bootstrap",
            ENABLE_LOTS_BOOTSTRAP,
            DateTrigger(run_date=datetime.now(timezone), timezone=timezone),
            "jobs.lots_full_load",
            ["--mode", "bootstrap"],
            LOTS_FULL_LOAD_TIMEOUT_SECONDS,
            "on startup",
        ),
        JobSpec(
            "lots_full_verify",
            ENABLE_LOTS_VERIFY,
            CronTrigger.from_crontab(LOTS_VERIFY_CRON, timezone=timezone),
            "jobs.lots_full_load",
            ["--mode", "verify"],
            LOTS_FULL_LOAD_TIMEOUT_SECONDS,
            LOTS_VERIFY_CRON,
        ),
        JobSpec(
            "lots_sync",
            ENABLE_LOTS_SYNC,
            CronTrigger.from_crontab(LOTS_SYNC_CRON, timezone=timezone),
            "jobs.lots_sync",
            [],
            LOTS_SYNC_TIMEOUT_SECONDS,
            LOTS_SYNC_CRON,
        ),
        JobSpec(
            "sitemap",
            ENABLE_SITEMAP,
            CronTrigger.from_crontab(SITEMAP_CRON, timezone=timezone),
            "jobs.sitemap_generator",
            [],
            SITEMAP_TIMEOUT_SECONDS,
            SITEMAP_CRON,
        ),
    ]


def build_scheduler() -> BlockingScheduler:
    timezone = ZoneInfo(SCHEDULER_TIMEZONE)
    scheduler = BlockingScheduler(timezone=timezone)
    for spec in scheduled_jobs(timezone):
        if not spec.enabled:
            logger.info(f"Job {spec.job_id} is disabled")
            continue
        scheduler.add_job(
            run_job,
            trigger=spec.trigger,
            args=[spec.job_id, spec.module, spec.args, spec.timeout],
            id=spec.job_id,
            name=spec.job_id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=MISFIRE_GRACE_SECONDS,
        )
    return scheduler


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    job_runs.mark_interrupted()
    job_runs.prune(JOB_RUNS_RETENTION_DAYS)
    scheduler = build_scheduler()

    def handle_signal(signum, _frame):
        logger.info(f"Received signal {signum}; stopping scheduler and running jobs")
        scheduler.shutdown(wait=False)
        with _children_lock:
            children = list(_children)
        for process in children:
            _stop(process)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    now = datetime.now(scheduler.timezone)
    for job in scheduler.get_jobs():
        next_run = job.trigger.get_next_fire_time(None, now)
        logger.info(
            f"Scheduled job {job.id}; next run at {next_run}",
            extra={"job_id": job.id, "trigger": str(job.trigger)},
        )
    scheduler.start()


if __name__ == "__main__":
    main()
