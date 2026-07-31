from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.db.models import TrashRotation, User
from bot.services import rotation, trash as trash_service
from bot.utils import pagination_keyboard

router = Router(name="trash")

_STATUS_LABELS = {
    "pending": strings.TRASH_STATUS_PENDING,
    "done": strings.TRASH_STATUS_DONE,
    "skipped_not_full": strings.TRASH_STATUS_SKIPPED,
}


@router.callback_query(trash_service.TrashCB.filter(F.action == "done"))
async def cb_trash_done(query: CallbackQuery, callback_data: trash_service.TrashCB, session: AsyncSession) -> None:
    ok, error = await trash_service.handle_done(session, query.bot, callback_data.log_id, query.from_user.id)
    await query.answer(strings.DONE_BUTTON_TOAST if ok else error, show_alert=not ok)


@router.callback_query(trash_service.TrashCB.filter(F.action == "skip"))
async def cb_trash_skip(query: CallbackQuery, callback_data: trash_service.TrashCB, session: AsyncSession) -> None:
    ok, error = await trash_service.handle_skip(session, query.bot, callback_data.log_id, query.from_user.id)
    await query.answer(strings.DONE_BUTTON_TOAST if ok else error, show_alert=not ok)


@router.message(F.text == strings.MENU_TRASH)
async def trash_menu(message: Message, session: AsyncSession) -> None:
    trash_type, log = await trash_service.get_today_info(session)
    if trash_type is None:
        await message.answer(strings.TRASH_NO_COLLECTION_TODAY)
        return
    if log is None:
        queue = await rotation.get_ordered_queue(session, TrashRotation)
        await message.answer(strings.TRASH_NO_HOUSEMATES if not queue else strings.TRASH_NOT_POSTED_YET)
        return
    user = await session.get(User, log.assigned_user_id)
    entry = strings.TRASH_HISTORY_ENTRY.format(
        date=log.date.isoformat(),
        trash_type=log.trash_type,
        assigned=user.display_name,
        status=_STATUS_LABELS[log.status],
    )
    await message.answer(f"{strings.TRASH_TODAY_STATUS_HEADER}\n{entry}")


async def _render_history_page(session: AsyncSession, page: int) -> tuple[str, object]:
    logs, has_next = await trash_service.get_history_page(session, page)
    if not logs and page == 0:
        return strings.NOTHING_TO_SHOW, None
    lines = []
    for log in logs:
        user = await session.get(User, log.assigned_user_id)
        lines.append(
            strings.TRASH_HISTORY_ENTRY.format(
                date=log.date.isoformat(),
                trash_type=log.trash_type,
                assigned=user.display_name,
                status=_STATUS_LABELS[log.status],
            )
        )
    text = "\n".join(lines) if lines else strings.NOTHING_TO_SHOW
    keyboard = pagination_keyboard("trash_hist", page, has_next)
    return text, keyboard


@router.message(Command("trash_history"))
async def trash_history(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _render_history_page(session, 0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("trash_hist:"))
async def trash_history_page(query: CallbackQuery, session: AsyncSession) -> None:
    page = int(query.data.split(":")[1])
    text, keyboard = await _render_history_page(session, page)
    await query.message.edit_text(text, reply_markup=keyboard)
    await query.answer()
