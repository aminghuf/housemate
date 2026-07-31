"""Typed accessors around the Settings key/value table."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Settings

TRASH_REMINDER_TIME = "trash_reminder_time"
TRASH_ALTERNATION_ANCHOR_DATE = "trash_alternation_anchor_date"
TRASH_CURRENT_POSITION = "trash_current_position"
CLEANING_REMINDER_WEEKDAY = "cleaning_reminder_weekday"  # 0=Monday .. 6=Sunday
CLEANING_REMINDER_TIME = "cleaning_reminder_time"
CLEANING_CURRENT_POSITION = "cleaning_current_position"

DEFAULTS = {
    TRASH_REMINDER_TIME: "08:00",
    CLEANING_REMINDER_WEEKDAY: "5",  # Saturday
    CLEANING_REMINDER_TIME: "21:00",
    TRASH_CURRENT_POSITION: "0",
    CLEANING_CURRENT_POSITION: "0",
}


async def get_setting(session: AsyncSession, key: str, default: str | None = None) -> str | None:
    row = await session.get(Settings, key)
    if row is not None:
        return row.value
    return DEFAULTS.get(key, default)


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(Settings, key)
    if row is None:
        row = Settings(key=key, value=value)
        session.add(row)
    else:
        row.value = value
        row.updated_at = dt.datetime.utcnow()
    await session.flush()


async def get_int(session: AsyncSession, key: str, default: int = 0) -> int:
    value = await get_setting(session, key)
    return int(value) if value is not None else default


async def get_trash_alternation_anchor(session: AsyncSession) -> dt.date:
    """First Tuesday the bot goes live; defaults to (and persists) the next
    upcoming Tuesday on first access, per spec §5.1."""
    value = await get_setting(session, TRASH_ALTERNATION_ANCHOR_DATE)
    if value is not None:
        return dt.date.fromisoformat(value)

    today = dt.date.today()
    days_until_tuesday = (1 - today.weekday()) % 7  # Monday=0 .. Tuesday=1
    anchor = today + dt.timedelta(days=days_until_tuesday)
    await set_setting(session, TRASH_ALTERNATION_ANCHOR_DATE, anchor.isoformat())
    return anchor
