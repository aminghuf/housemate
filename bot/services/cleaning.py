from __future__ import annotations

import datetime as dt
import html
from typing import Sequence

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import CleaningLog, CleaningRotation, User
from bot.services import rotation, settings_store
from bot.utils import format_dt, mention

KITCHEN = "kitchen"
HALL = "hall"
BATHROOM = "bathroom"
SECTION_ORDER = [KITCHEN, HALL, BATHROOM]
SECTION_LABELS = {
    KITCHEN: strings.CLEANING_SECTION_KITCHEN,
    HALL: strings.CLEANING_SECTION_HALL,
    BATHROOM: strings.CLEANING_SECTION_BATHROOM,
}


class CleaningCB(CallbackData, prefix="clean"):
    action: str  # "done" or "skip"
    log_id: int


def assign_sections(queue: Sequence, position: int) -> dict[str, object]:
    """Pure round-robin section assignment (spec §8). With fewer than 3
    active housemates the queue wraps, so someone ends up assigned 2
    sections that week — accepted per spec §13.3."""
    return {section: rotation.user_at(queue, position + i) for i, section in enumerate(SECTION_ORDER)}


def next_cleaning_day(today: dt.date) -> dt.date:
    """The upcoming Sunday (or today, if today already is Sunday) — used as
    week_start_date, i.e. the date the assignments are *for*."""
    days_ahead = (6 - today.weekday()) % 7
    return today + dt.timedelta(days=days_ahead)


async def create_weekly_assignments_and_post(
    bot: Bot, session: AsyncSession, *, today: dt.date | None = None
) -> list[CleaningLog]:
    week_start = next_cleaning_day(today or dt.date.today())

    queue = await rotation.get_ordered_queue(session, CleaningRotation)
    if not queue:
        return []

    position = await settings_store.get_int(session, settings_store.CLEANING_CURRENT_POSITION, 0)
    assignments = assign_sections(queue, position)

    logs = []
    for section in SECTION_ORDER:
        row = assignments[section]
        log = CleaningLog(week_start_date=week_start, user_id=row.user_id, section=section, status="pending")
        session.add(log)
        logs.append(log)
    await session.flush()

    new_position = rotation.advance_position(position, len(queue), step=3)
    await settings_store.set_setting(session, settings_store.CLEANING_CURRENT_POSITION, str(new_position))

    text, keyboard = await _render_message(session, logs)
    message = await bot.send_message(settings.house_channel_id, text, reply_markup=keyboard, parse_mode="HTML")
    for log in logs:
        log.message_id = message.message_id
    await session.flush()
    return logs


async def _render_message(session: AsyncSession, logs: Sequence[CleaningLog]) -> tuple[str, InlineKeyboardMarkup | None]:
    ordered = sorted(logs, key=lambda log: SECTION_ORDER.index(log.section))
    lines = [strings.CLEANING_HEADER]
    keyboard_rows = []

    for log in ordered:
        user = await session.get(User, log.user_id)
        section_label = SECTION_LABELS[log.section]
        if log.status == "pending":
            lines.append(strings.CLEANING_SECTION_PENDING_LINE.format(section=section_label, mention=mention(user)))
            keyboard_rows.append(
                [
                    InlineKeyboardButton(
                        text=strings.BTN_CLEANING_DONE,
                        callback_data=CleaningCB(action="done", log_id=log.id).pack(),
                    ),
                    InlineKeyboardButton(
                        text=strings.BTN_CLEANING_NOT_NEEDED,
                        callback_data=CleaningCB(action="skip", log_id=log.id).pack(),
                    ),
                ]
            )
        elif log.status == "done":
            lines.append(
                strings.CLEANING_SECTION_DONE_LINE.format(
                    section=section_label, name=html.escape(user.display_name), timestamp=format_dt(log.responded_at)
                )
            )
        else:
            lines.append(
                strings.CLEANING_SECTION_SKIPPED_LINE.format(
                    section=section_label, name=html.escape(user.display_name), timestamp=format_dt(log.responded_at)
                )
            )

    text = "\n".join(lines)
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_rows) if keyboard_rows else None
    return text, keyboard


async def handle_response(
    session: AsyncSession, bot: Bot, log_id: int, action: str, acting_user_id: int
) -> tuple[bool, str]:
    log = await session.get(CleaningLog, log_id)
    if log is None:
        return False, strings.NOTHING_TO_SHOW
    if log.user_id != acting_user_id:
        return False, strings.NOT_YOUR_TURN
    if log.status != "pending":
        return False, strings.ALREADY_HANDLED

    log.status = "done" if action == "done" else "skipped_not_needed"
    log.responded_at = dt.datetime.utcnow()
    await session.flush()

    siblings = (
        await session.execute(select(CleaningLog).where(CleaningLog.message_id == log.message_id))
    ).scalars().all()
    text, keyboard = await _render_message(session, siblings)
    await bot.edit_message_text(
        chat_id=settings.house_channel_id, message_id=log.message_id, text=text, reply_markup=keyboard, parse_mode="HTML"
    )
    return True, ""


async def get_current_week_logs(session: AsyncSession) -> list[CleaningLog]:
    latest = (
        await session.execute(select(CleaningLog.week_start_date).order_by(CleaningLog.week_start_date.desc()).limit(1))
    ).scalar()
    if latest is None:
        return []
    result = await session.execute(select(CleaningLog).where(CleaningLog.week_start_date == latest))
    return sorted(result.scalars().all(), key=lambda log: SECTION_ORDER.index(log.section))


async def get_history_page(session: AsyncSession, page: int, page_size: int = 5) -> tuple[list[CleaningLog], bool]:
    result = await session.execute(
        select(CleaningLog)
        .order_by(CleaningLog.week_start_date.desc(), CleaningLog.id.desc())
        .offset(page * page_size)
        .limit(page_size + 1)
    )
    rows = list(result.scalars().all())
    has_next = len(rows) > page_size
    return rows[:page_size], has_next
