from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import CleaningRotation, TrashRotation
from bot.handlers import admin_ui
from bot.scheduler import jobs
from bot.services import admin as admin_service
from bot.services import rotation, settings_store

router = Router(name="admin")


class Announce(StatesGroup):
    text = State()
    confirm = State()


async def _require_admin(message: Message) -> bool:
    if message.from_user.id not in settings.admin_id_set:
        await message.answer(strings.NOT_ADMIN)
        return False
    return True


@router.message(F.text == strings.MENU_ADMIN)
async def admin_menu(message: Message) -> None:
    if not await _require_admin(message):
        return
    # Panel buttons (housemates / rotations / announce) live in admin_ui.
    await message.answer(strings.ADMIN_MENU_TEXT, reply_markup=admin_ui.admin_panel_keyboard())


async def _send_announce_preview(message: Message, text: str) -> None:
    preview = strings.ADMIN_ANNOUNCE_PREVIEW.format(text=html.escape(text))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=strings.CONFIRM_YES, callback_data="announce_confirm:yes"),
                InlineKeyboardButton(text=strings.CONFIRM_CANCEL, callback_data="announce_confirm:no"),
            ]
        ]
    )
    await message.answer(preview, reply_markup=kb, parse_mode="HTML")


@router.message(Command("announce"), StateFilter(None))
async def cmd_announce(message: Message, state: FSMContext, command: CommandObject) -> None:
    if not await _require_admin(message):
        return
    if command.args:
        text = command.args.strip()
        await state.update_data(text=text)
        await state.set_state(Announce.confirm)
        await _send_announce_preview(message, text)
        return
    await state.set_state(Announce.text)
    await message.answer(strings.ADMIN_ANNOUNCE_ASK_TEXT)


@router.callback_query(StateFilter(None), F.data == "admin_menu:announce")
async def start_announce_from_menu(query: CallbackQuery, state: FSMContext) -> None:
    if query.from_user.id not in settings.admin_id_set:
        await query.answer(strings.NOT_ADMIN, show_alert=True)
        return
    await state.set_state(Announce.text)
    await query.answer()
    await query.message.answer(strings.ADMIN_ANNOUNCE_ASK_TEXT)


@router.message(Announce.text)
async def process_announce_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(strings.ADMIN_ANNOUNCE_ASK_TEXT)
        return
    await state.update_data(text=text)
    await state.set_state(Announce.confirm)
    await _send_announce_preview(message, text)


@router.callback_query(Announce.confirm, F.data.startswith("announce_confirm:"))
async def confirm_announce(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    action = query.data.split(":")[1]
    if action == "no":
        await state.clear()
        await query.answer()
        await query.message.answer(strings.ADMIN_ANNOUNCE_CANCELLED)
        return

    data = await state.get_data()
    text = data["text"]
    await query.bot.send_message(
        settings.house_channel_id,
        strings.ADMIN_ANNOUNCE_CHANNEL_POST.format(text=html.escape(text)),
        parse_mode="HTML",
    )
    await admin_service.log_action(session, query.from_user.id, "announce", text[:200])
    await state.clear()
    await query.answer()
    await query.message.answer(strings.ADMIN_ANNOUNCE_POSTED)


@router.message(Command("set_trash_reminder_time"))
async def set_trash_reminder_time(message: Message, session: AsyncSession, command: CommandObject) -> None:
    if not await _require_admin(message):
        return
    parsed = admin_service.parse_time(command.args)
    if parsed is None:
        await message.answer(strings.ADMIN_INVALID_TIME)
        return
    hour, minute = parsed
    time_str = command.args.strip()
    await settings_store.set_setting(session, settings_store.TRASH_REMINDER_TIME, time_str)
    jobs.reschedule_trash(hour, minute)
    await admin_service.log_action(session, message.from_user.id, "set_trash_reminder_time", time_str)
    await message.answer(strings.ADMIN_TRASH_TIME_SET.format(time=time_str))


@router.message(Command("set_cleaning_reminder"))
async def set_cleaning_reminder(message: Message, session: AsyncSession, command: CommandObject) -> None:
    if not await _require_admin(message):
        return
    parts = (command.args or "").split()
    if len(parts) != 2:
        await message.answer(strings.ADMIN_INVALID_WEEKDAY)
        return
    weekday_text, time_text = parts
    weekday = admin_service.parse_weekday(weekday_text)
    if weekday is None:
        await message.answer(strings.ADMIN_INVALID_WEEKDAY)
        return
    parsed_time = admin_service.parse_time(time_text)
    if parsed_time is None:
        await message.answer(strings.ADMIN_INVALID_TIME)
        return

    hour, minute = parsed_time
    await settings_store.set_setting(session, settings_store.CLEANING_REMINDER_WEEKDAY, str(weekday))
    await settings_store.set_setting(session, settings_store.CLEANING_REMINDER_TIME, time_text)
    jobs.reschedule_cleaning(weekday, hour, minute)
    details = f"{weekday_text} {time_text}"
    await admin_service.log_action(session, message.from_user.id, "set_cleaning_reminder", details)
    await message.answer(
        strings.ADMIN_CLEANING_REMINDER_SET.format(weekday=strings.WEEKDAY_LABELS_FA[weekday], time=time_text)
    )


@router.message(Command("set_cleaning_nag_time"))
async def set_cleaning_nag_time(message: Message, session: AsyncSession, command: CommandObject) -> None:
    if not await _require_admin(message):
        return
    parsed = admin_service.parse_time(command.args)
    if parsed is None:
        await message.answer(strings.ADMIN_INVALID_TIME)
        return
    hour, minute = parsed
    time_str = command.args.strip()
    await settings_store.set_setting(session, settings_store.CLEANING_NAG_TIME, time_str)
    jobs.reschedule_cleaning_nag(hour, minute)
    await admin_service.log_action(session, message.from_user.id, "set_cleaning_nag_time", time_str)
    await message.answer(strings.ADMIN_CLEANING_NAG_TIME_SET.format(time=time_str))


async def _rotation_command(
    message: Message, session: AsyncSession, command: CommandObject, model: type, kind: str
) -> None:
    if not await _require_admin(message):
        return

    args = (command.args or "").split()
    if not args:
        # Show the interactive panel instead of a static list. (The old
        # listing read `row.user`, a lazily-loaded relationship, which
        # raises MissingGreenlet on the async session.)
        text, keyboard = await admin_ui.render_rotation(session, kind)
        await message.answer(text, reply_markup=keyboard)
        return

    try:
        new_order = [int(x) for x in args]
    except ValueError:
        await message.answer(strings.ADMIN_ROTATION_USAGE)
        return

    error = await admin_service.reorder_rotation(session, model, new_order)
    if error:
        await message.answer(error)
        return

    await admin_service.log_action(session, message.from_user.id, f"reorder_{model.__tablename__}", " ".join(args))
    await message.answer(strings.ADMIN_ROTATION_REORDERED)


@router.message(Command("trash_rotation"))
async def trash_rotation(message: Message, session: AsyncSession, command: CommandObject) -> None:
    await _rotation_command(message, session, command, TrashRotation, admin_ui.TRASH)


@router.message(Command("cleaning_rotation"))
async def cleaning_rotation(message: Message, session: AsyncSession, command: CommandObject) -> None:
    await _rotation_command(message, session, command, CleaningRotation, admin_ui.CLEANING)


@router.message(Command("setup_rotation"))
async def setup_rotation(message: Message, session: AsyncSession, command: CommandObject) -> None:
    if not await _require_admin(message):
        return
    args = (command.args or "").split()
    if not args:
        await message.answer(strings.ADMIN_ROTATION_USAGE)
        return
    try:
        new_order = [int(x) for x in args]
    except ValueError:
        await message.answer(strings.ADMIN_ROTATION_USAGE)
        return

    error = await admin_service.reorder_rotation(session, TrashRotation, new_order)
    if error:
        await message.answer(error)
        return

    await admin_service.log_action(session, message.from_user.id, "setup_rotation", " ".join(args))
    await message.answer(strings.ADMIN_ROTATION_REORDERED)


@router.message(Command("add_housemate"))
async def add_housemate(message: Message, session: AsyncSession, command: CommandObject) -> None:
    if not await _require_admin(message):
        return
    parts = (command.args or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[0].isdigit():
        await message.answer(strings.ADMIN_HOUSEMATE_USAGE)
        return
    telegram_id, display_name = int(parts[0]), parts[1].strip()
    user = await admin_service.add_housemate(session, telegram_id, display_name)
    await admin_service.log_action(session, message.from_user.id, "add_housemate", str(telegram_id))
    await message.answer(strings.ADMIN_HOUSEMATE_ADDED.format(name=user.display_name))


@router.message(Command("remove_housemate"))
async def remove_housemate(message: Message, session: AsyncSession, command: CommandObject) -> None:
    if not await _require_admin(message):
        return
    args = (command.args or "").split()
    if len(args) != 1 or not args[0].isdigit():
        await message.answer(strings.ADMIN_REMOVE_HOUSEMATE_USAGE)
        return
    telegram_id = int(args[0])
    user = await admin_service.remove_housemate(session, telegram_id)
    if user is None:
        await message.answer(strings.ADMIN_HOUSEMATE_NOT_FOUND)
        return
    await admin_service.log_action(session, message.from_user.id, "remove_housemate", str(telegram_id))
    await message.answer(strings.ADMIN_HOUSEMATE_REMOVED.format(name=user.display_name))
