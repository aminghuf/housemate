from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import settings
from bot.db.session import async_session_factory
from bot.handlers import admin, bills, cleaning, onboarding, shopping, trash
from bot.middlewares.db import DBSessionMiddleware
from bot.middlewares.membership import MembershipMiddleware
from bot.scheduler import jobs
from bot.services import settings_store

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_scheduler() -> AsyncIOScheduler:
    # A separate sync sqlite URL (no aiosqlite driver) — APScheduler's
    # SQLAlchemyJobStore uses a synchronous engine internally, independent
    # of the app's async engine, so the two can safely share one file.
    jobstore_url = f"sqlite:///{settings.db_path}"
    return AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=jobstore_url)},
        timezone=settings.timezone,
    )


async def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    async with async_session_factory() as session:
        trash_time = await settings_store.get_setting(session, settings_store.TRASH_REMINDER_TIME)
        cleaning_time = await settings_store.get_setting(session, settings_store.CLEANING_REMINDER_TIME)
        cleaning_weekday = await settings_store.get_int(session, settings_store.CLEANING_REMINDER_WEEKDAY)
        nag_time = await settings_store.get_setting(session, settings_store.CLEANING_NAG_TIME)
        await session.commit()

    trash_hour, trash_minute = (int(x) for x in trash_time.split(":"))
    cleaning_hour, cleaning_minute = (int(x) for x in cleaning_time.split(":"))
    nag_hour, nag_minute = (int(x) for x in nag_time.split(":"))

    jobs.register_trash_job(scheduler, trash_hour, trash_minute, settings.timezone)
    jobs.register_cleaning_job(scheduler, cleaning_weekday, cleaning_hour, cleaning_minute, settings.timezone)
    jobs.register_cleaning_nag_job(scheduler, nag_hour, nag_minute, settings.timezone)


def _build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Registration order matters: DB session must be available before the
    # membership check runs, so it's registered first (outermost).
    dp.message.outer_middleware(DBSessionMiddleware())
    dp.callback_query.outer_middleware(DBSessionMiddleware())
    dp.message.outer_middleware(MembershipMiddleware())
    dp.callback_query.outer_middleware(MembershipMiddleware())

    dp.include_router(onboarding.router)
    dp.include_router(trash.router)
    dp.include_router(bills.router)
    dp.include_router(shopping.router)
    dp.include_router(cleaning.router)
    dp.include_router(admin.router)

    return dp


async def main() -> None:
    if settings.run_mode != "polling":
        raise NotImplementedError(f"RUN_MODE={settings.run_mode!r} is not wired up yet; use 'polling'")

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties())
    dp = _build_dispatcher()

    jobs.set_bot(bot)
    scheduler = _build_scheduler()
    jobs.set_scheduler(scheduler)
    await _register_jobs(scheduler)
    scheduler.start()

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
