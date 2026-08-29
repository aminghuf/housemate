"""Scheduled jobs. Job functions take no arguments (other than what they look
up themselves) so they stay picklable for the persistent APScheduler job
store — the live `Bot` instance is kept in a module-level singleton instead
of being passed as a job argument.
"""
from __future__ import annotations

import datetime as dt

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from aiogram import Bot

from bot.config import settings
from bot.db.session import async_session_factory
from bot.services import cleaning as cleaning_service
from bot.services import trash as trash_service
from bot.utils import now_local

TRASH_JOB_ID = "trash_daily_reminder"
CLEANING_JOB_ID = "cleaning_weekly_reminder"
CLEANING_NAG_JOB_ID = "cleaning_daily_nag"

_bot: Bot | None = None
_scheduler: AsyncIOScheduler | None = None


def set_bot(bot: Bot) -> None:
    global _bot
    _bot = bot


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    global _scheduler
    _scheduler = scheduler


def reschedule_trash(hour: int, minute: int) -> None:
    assert _scheduler is not None
    register_trash_job(_scheduler, hour, minute, settings.timezone)


def reschedule_cleaning(weekday: int, hour: int, minute: int) -> None:
    assert _scheduler is not None
    register_cleaning_job(_scheduler, weekday, hour, minute, settings.timezone)


def reschedule_cleaning_nag(hour: int, minute: int) -> None:
    assert _scheduler is not None
    register_cleaning_nag_job(_scheduler, hour, minute, settings.timezone)


async def run_trash_job() -> None:
    """Fires the evening before each collection day (see
    register_trash_job) and posts the reminder for *tomorrow's* trash,
    so housemates can take it out the night before."""
    assert _bot is not None
    tomorrow = now_local().date() + dt.timedelta(days=1)
    async with async_session_factory() as session:
        await trash_service.create_daily_log_and_post(_bot, session, date=tomorrow)
        await session.commit()


async def run_cleaning_job() -> None:
    assert _bot is not None
    async with async_session_factory() as session:
        await cleaning_service.create_weekly_assignments_and_post(_bot, session)
        await session.commit()


async def run_cleaning_nag_job() -> None:
    """Daily chase-up for cleaning sections nobody has ticked off yet.
    Posts nothing when everything is already handled."""
    assert _bot is not None
    async with async_session_factory() as session:
        await cleaning_service.post_pending_nag(_bot, session)
        await session.commit()


def register_trash_job(scheduler: AsyncIOScheduler, hour: int, minute: int, timezone: str) -> None:
    # Fires the evening *before* each collection day (Mon-Sat), i.e. every
    # day except Saturday — Saturday's reminder would be for Sunday, which
    # has no collection (spec §5.1).
    scheduler.add_job(
        run_trash_job,
        CronTrigger(day_of_week="sun,mon,tue,wed,thu,fri", hour=hour, minute=minute, timezone=timezone),
        id=TRASH_JOB_ID,
        replace_existing=True,
    )


def register_cleaning_job(scheduler: AsyncIOScheduler, weekday: int, hour: int, minute: int, timezone: str) -> None:
    # APScheduler cron day_of_week: mon=0 .. sun=6, matching Python's date.weekday()
    scheduler.add_job(
        run_cleaning_job,
        CronTrigger(day_of_week=weekday, hour=hour, minute=minute, timezone=timezone),
        id=CLEANING_JOB_ID,
        replace_existing=True,
    )


def register_cleaning_nag_job(scheduler: AsyncIOScheduler, hour: int, minute: int, timezone: str) -> None:
    # Runs every day; the job itself no-ops unless something is outstanding,
    # and it skips the not-yet-arrived week so it can't double up with the
    # weekly announcement posted the evening before cleaning day.
    scheduler.add_job(
        run_cleaning_nag_job,
        CronTrigger(hour=hour, minute=minute, timezone=timezone),
        id=CLEANING_NAG_JOB_ID,
        replace_existing=True,
    )
