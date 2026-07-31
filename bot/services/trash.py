from __future__ import annotations

import datetime as dt

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import TrashLog, TrashRotation, User
from bot.services import rotation, settings_store, trash_schedule
from bot.utils import mention, now_str


class TrashCB(CallbackData, prefix="trash"):
    action: str  # "done" or "skip"
    log_id: int


def _keyboard(log_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=strings.BTN_TRASH_DONE, callback_data=TrashCB(action="done", log_id=log_id).pack()
                ),
                InlineKeyboardButton(
                    text=strings.BTN_TRASH_NOT_NEEDED,
                    callback_data=TrashCB(action="skip", log_id=log_id).pack(),
                ),
            ]
        ]
    )


async def create_daily_log_and_post(bot: Bot, session: AsyncSession, *, date: dt.date | None = None) -> TrashLog | None:
    date = date or dt.date.today()
    anchor = await settings_store.get_trash_alternation_anchor(session)
    trash_type = trash_schedule.get_trash_type(date, anchor)
    if trash_type is None:
        return None

    queue = await rotation.get_ordered_queue(session, TrashRotation)
    if not queue:
        return None

    position = await settings_store.get_int(session, settings_store.TRASH_CURRENT_POSITION, 0)
    assigned = rotation.user_at(queue, position)

    log = TrashLog(date=date, trash_type=trash_type, assigned_user_id=assigned.user_id, status="pending")
    session.add(log)
    await session.flush()

    user = await session.get(User, assigned.user_id)
    text = strings.TRASH_REMINDER.format(mention=mention(user), trash_type=trash_type)
    message = await bot.send_message(
        settings.house_channel_id, text, reply_markup=_keyboard(log.id), parse_mode="HTML"
    )
    log.message_id = message.message_id
    await session.flush()
    return log


async def handle_done(session: AsyncSession, bot: Bot, log_id: int, acting_user_id: int) -> tuple[bool, str]:
    log = await session.get(TrashLog, log_id)
    if log is None:
        return False, strings.NOTHING_TO_SHOW
    if log.assigned_user_id != acting_user_id:
        return False, strings.NOT_YOUR_TURN
    if log.status != "pending":
        return False, strings.ALREADY_HANDLED

    log.status = "done"
    log.responded_at = dt.datetime.utcnow()
    await session.flush()

    queue = await rotation.get_ordered_queue(session, TrashRotation)
    position = await settings_store.get_int(session, settings_store.TRASH_CURRENT_POSITION, 0)
    new_position = rotation.advance_position(position, len(queue))
    await settings_store.set_setting(session, settings_store.TRASH_CURRENT_POSITION, str(new_position))

    user = await session.get(User, acting_user_id)
    text = strings.TRASH_DONE_CONFIRMATION.format(
        trash_type=log.trash_type, mention=mention(user), timestamp=now_str()
    )
    await bot.edit_message_text(
        chat_id=settings.house_channel_id, message_id=log.message_id, text=text, parse_mode="HTML"
    )
    return True, ""


async def handle_skip(session: AsyncSession, bot: Bot, log_id: int, acting_user_id: int) -> tuple[bool, str]:
    log = await session.get(TrashLog, log_id)
    if log is None:
        return False, strings.NOTHING_TO_SHOW
    if log.assigned_user_id != acting_user_id:
        return False, strings.NOT_YOUR_TURN
    if log.status != "pending":
        return False, strings.ALREADY_HANDLED

    log.status = "skipped_not_full"
    log.responded_at = dt.datetime.utcnow()
    await session.flush()
    # current_position intentionally does NOT advance here — same person is
    # re-asked next collection day (spec §5.2 / §13.1).

    user = await session.get(User, acting_user_id)
    text = strings.TRASH_SKIPPED_CONFIRMATION.format(mention=mention(user), timestamp=now_str())
    await bot.edit_message_text(
        chat_id=settings.house_channel_id, message_id=log.message_id, text=text, parse_mode="HTML"
    )
    return True, ""


async def get_today_log(session: AsyncSession, date: dt.date | None = None) -> TrashLog | None:
    date = date or dt.date.today()
    result = await session.execute(select(TrashLog).where(TrashLog.date == date))
    return result.scalars().first()


async def get_today_info(session: AsyncSession, date: dt.date | None = None) -> tuple[str | None, TrashLog | None]:
    """Returns (today's trash type or None if no collection, today's log or
    None if not posted yet) — lets callers tell "no collection today" apart
    from "reminder just hasn't fired yet"."""
    date = date or dt.date.today()
    anchor = await settings_store.get_trash_alternation_anchor(session)
    trash_type = trash_schedule.get_trash_type(date, anchor)
    log = await get_today_log(session, date)
    return trash_type, log


async def get_history_page(session: AsyncSession, page: int, page_size: int = 5) -> tuple[list[TrashLog], bool]:
    result = await session.execute(
        select(TrashLog).order_by(TrashLog.date.desc(), TrashLog.id.desc()).offset(page * page_size).limit(page_size + 1)
    )
    rows = list(result.scalars().all())
    has_next = len(rows) > page_size
    return rows[:page_size], has_next
