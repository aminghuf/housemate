from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.db.models import CleaningRotation, User
from bot.services import cleaning as cleaning_service, rotation
from bot.utils import pagination_keyboard

router = Router(name="cleaning")

_STATUS_LABELS = {
    "pending": strings.CLEANING_STATUS_PENDING,
    "done": strings.CLEANING_STATUS_DONE,
    "skipped_not_needed": strings.CLEANING_STATUS_SKIPPED,
}


@router.callback_query(cleaning_service.CleaningCB.filter(F.action == "done"))
async def cb_cleaning_done(query: CallbackQuery, callback_data: cleaning_service.CleaningCB, session: AsyncSession) -> None:
    ok, error = await cleaning_service.handle_response(session, query.bot, callback_data.log_id, "done", query.from_user.id)
    await query.answer(strings.DONE_BUTTON_TOAST if ok else error, show_alert=not ok)


@router.callback_query(cleaning_service.CleaningCB.filter(F.action == "skip"))
async def cb_cleaning_skip(query: CallbackQuery, callback_data: cleaning_service.CleaningCB, session: AsyncSession) -> None:
    ok, error = await cleaning_service.handle_response(session, query.bot, callback_data.log_id, "skip", query.from_user.id)
    await query.answer(strings.DONE_BUTTON_TOAST if ok else error, show_alert=not ok)


@router.message(F.text == strings.MENU_CLEANING)
async def cleaning_menu(message: Message, session: AsyncSession) -> None:
    logs = await cleaning_service.get_current_week_logs(session)
    if not logs:
        queue = await rotation.get_ordered_queue(session, CleaningRotation)
        await message.answer(strings.CLEANING_NO_HOUSEMATES if not queue else strings.CLEANING_THIS_WEEK_EMPTY)
        return

    lines = [strings.CLEANING_HEADER]
    for log in logs:
        user = await session.get(User, log.user_id)
        section_label = cleaning_service.SECTION_LABELS[log.section]
        status = _STATUS_LABELS[log.status]
        lines.append(f"{section_label}: {user.display_name} — {status}")
    await message.answer("\n".join(lines))


async def _render_history_page(session: AsyncSession, page: int):
    logs, has_next = await cleaning_service.get_history_page(session, page)
    if not logs and page == 0:
        return strings.NOTHING_TO_SHOW, None
    lines = []
    for log in logs:
        user = await session.get(User, log.user_id)
        lines.append(
            strings.CLEANING_HISTORY_ENTRY.format(
                week=log.week_start_date.isoformat(),
                section=cleaning_service.SECTION_LABELS[log.section],
                name=user.display_name,
                status=_STATUS_LABELS[log.status],
            )
        )
    text = "\n".join(lines) if lines else strings.NOTHING_TO_SHOW
    keyboard = pagination_keyboard("clean_hist", page, has_next)
    return text, keyboard


@router.message(Command("cleaning_history"))
async def cleaning_history(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _render_history_page(session, 0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("clean_hist:"))
async def cleaning_history_page(query: CallbackQuery, session: AsyncSession) -> None:
    page = int(query.data.split(":")[1])
    text, keyboard = await _render_history_page(session, page)
    await query.message.edit_text(text, reply_markup=keyboard)
    await query.answer()
