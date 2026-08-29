from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass
from typing import Sequence

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import CleaningLog, CleaningRotation, User
from bot.services import rotation, settings_store
from bot.utils import format_dt, mention, now_local

KITCHEN = "kitchen"
HALL = "hall"
BATHROOM = "bathroom"
SECTION_ORDER = [KITCHEN, HALL, BATHROOM]
# Terminal status for a section that was never responded to before its week
# rolled over (see _close_out_stale_pending).
MISSED = "missed"
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


def weekly_rotation_step(queue_length: int) -> int:
    """How far to advance the cleaning queue each week.

    The natural step is 3 (a fresh trio each week), but when the queue
    length divides 3 — i.e. exactly 1 or 3 housemates — `(pos + 3) % n`
    lands back on `pos`, freezing the rotation so everyone keeps the same
    section week after week. Falling back to a step of 1 keeps people
    cycling through the sections instead.
    """
    if queue_length <= 0:
        return 0
    return 3 if 3 % queue_length != 0 else 1


async def _close_out_stale_pending(session: AsyncSession, before: dt.date) -> None:
    """Marks still-pending sections from earlier weeks as `missed`, so a
    week nobody responded to doesn't linger as the "current" week and
    doesn't keep triggering the daily nag once a new week has started."""
    stale = (
        await session.execute(
            select(CleaningLog).where(CleaningLog.week_start_date < before, CleaningLog.status == "pending")
        )
    ).scalars().all()
    for log in stale:
        log.status = MISSED
    if stale:
        await session.flush()


async def create_weekly_assignments_and_post(
    bot: Bot, session: AsyncSession, *, today: dt.date | None = None
) -> list[CleaningLog]:
    week_start = next_cleaning_day(today or now_local().date())

    already_posted = (
        await session.execute(select(CleaningLog).where(CleaningLog.week_start_date == week_start))
    ).scalars().first()
    if already_posted is not None:
        # Already announced for this week — don't post a duplicate, and
        # don't advance the queue a second time.
        return []

    queue = await rotation.get_ordered_queue(session, CleaningRotation)
    if not queue:
        return []

    await _close_out_stale_pending(session, week_start)

    position = await settings_store.get_int(session, settings_store.CLEANING_CURRENT_POSITION, 0)
    assignments = assign_sections(queue, position)

    logs = []
    for section in SECTION_ORDER:
        row = assignments[section]
        log = CleaningLog(week_start_date=week_start, user_id=row.user_id, section=section, status="pending")
        session.add(log)
        logs.append(log)
    await session.flush()

    # Advances unconditionally — a week nobody finished must still hand the
    # sections on to the next people rather than repeating the same trio.
    step = weekly_rotation_step(len(queue))
    new_position = rotation.advance_position(position, len(queue), step=step)
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
            doer = await session.get(User, log.completed_by_user_id) if log.completed_by_user_id else user
            line = strings.CLEANING_SECTION_DONE_LINE.format(
                section=section_label, name=html.escape(doer.display_name), timestamp=format_dt(log.responded_at)
            )
            if log.completed_by_user_id and log.completed_by_user_id != log.user_id:
                line += strings.VOLUNTEER_INLINE_SUFFIX.format(assigned_name=html.escape(user.display_name))
            lines.append(line)
        elif log.status == MISSED:
            # Never responded to before the week rolled over, so there's no
            # responded_at timestamp to show.
            lines.append(
                strings.CLEANING_SECTION_MISSED_LINE.format(
                    section=section_label, name=html.escape(user.display_name)
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
    """"✅ تمیز کردم" can be tapped by anyone — covering someone else's
    section is a normal, recordable action (spec update: "voluntarily do a
    job"). "➖ نیازی نبود" stays restricted to the assigned housemate, since
    that's a judgment call tied to their specific section that week."""
    log = await session.get(CleaningLog, log_id)
    if log is None:
        return False, strings.NOTHING_TO_SHOW
    if log.status != "pending":
        return False, strings.ALREADY_HANDLED
    if action == "skip" and log.user_id != acting_user_id:
        return False, strings.NOT_YOUR_TURN

    log.status = "done" if action == "done" else "skipped_not_needed"
    log.responded_at = dt.datetime.utcnow()
    if action == "done":
        log.completed_by_user_id = acting_user_id
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


@dataclass
class NextWeekCleaning:
    date: dt.date
    assignments: dict[str, tuple[User | None, str | None]]  # section -> (user, status or None if projected)
    is_projected: bool


async def get_next_week_assignments(session: AsyncSession, today: dt.date | None = None) -> NextWeekCleaning:
    """Who cleans *next* cleaning week — the Sunday after whatever week is
    currently posted, or the upcoming Sunday if nothing is posted yet.

    In both cases the stored position already points at the trio that
    hasn't been assigned yet (it advances the moment a week is posted), so
    projecting straight off `position` is correct.
    """
    today = today or now_local().date()
    upcoming = next_cleaning_day(today)

    latest = (
        await session.execute(
            select(CleaningLog.week_start_date).order_by(CleaningLog.week_start_date.desc()).limit(1)
        )
    ).scalar()
    target = latest + dt.timedelta(days=7) if latest is not None and latest >= upcoming else upcoming

    existing = (
        await session.execute(select(CleaningLog).where(CleaningLog.week_start_date == target))
    ).scalars().all()
    if existing:
        assignments: dict[str, tuple[User | None, str | None]] = {}
        for log in sorted(existing, key=lambda log: SECTION_ORDER.index(log.section)):
            assignments[log.section] = (await session.get(User, log.user_id), log.status)
        return NextWeekCleaning(date=target, assignments=assignments, is_projected=False)

    queue = await rotation.get_ordered_queue(session, CleaningRotation)
    if not queue:
        return NextWeekCleaning(date=target, assignments={}, is_projected=True)

    position = await settings_store.get_int(session, settings_store.CLEANING_CURRENT_POSITION, 0)
    assignments = {}
    for section, row in assign_sections(queue, position).items():
        assignments[section] = (await session.get(User, row.user_id), None)
    return NextWeekCleaning(date=target, assignments=assignments, is_projected=True)


async def get_pending_logs_for_nag(session: AsyncSession, today: dt.date | None = None) -> list[CleaningLog]:
    """Sections still pending for a cleaning week that has already arrived.

    Future weeks are excluded so the nag doesn't fire on the same evening
    the assignments were announced, and `missed` weeks are excluded because
    _close_out_stale_pending has already retired them.
    """
    today = today or now_local().date()
    result = await session.execute(
        select(CleaningLog).where(CleaningLog.week_start_date <= today, CleaningLog.status == "pending")
    )
    return sorted(
        result.scalars().all(), key=lambda log: (log.week_start_date, SECTION_ORDER.index(log.section))
    )


async def post_pending_nag(bot: Bot, session: AsyncSession, today: dt.date | None = None) -> bool:
    """Posts one channel reminder listing every section still not ticked.
    Returns False (posting nothing) when there's nothing outstanding."""
    logs = await get_pending_logs_for_nag(session, today)
    if not logs:
        return False

    lines = [strings.CLEANING_NAG_HEADER]
    for log in logs:
        user = await session.get(User, log.user_id)
        lines.append(strings.CLEANING_NAG_LINE.format(section=SECTION_LABELS[log.section], mention=mention(user)))
    lines.append("")
    lines.append(strings.CLEANING_NAG_FOOTER)
    text = "\n".join(lines)

    # Reply to the original assignment post where possible, so its buttons
    # are one tap away instead of buried further up the channel.
    reply_to = next((log.message_id for log in logs if log.message_id), None)
    try:
        await bot.send_message(
            settings.house_channel_id, text, parse_mode="HTML", reply_to_message_id=reply_to
        )
    except TelegramBadRequest:
        # Original post was deleted — send it unthreaded rather than lose the nag.
        await bot.send_message(settings.house_channel_id, text, parse_mode="HTML")
    return True


