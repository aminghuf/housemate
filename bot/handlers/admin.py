from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import CleaningRotation, TrashRotation
from bot.scheduler import jobs
from bot.services import admin as admin_service
from bot.services import rotation, settings_store

router = Router(name="admin")


async def _require_admin(message: Message) -> bool:
    if message.from_user.id not in settings.admin_id_set:
        await message.answer(strings.NOT_ADMIN)
        return False
    return True


@router.message(F.text == strings.MENU_ADMIN)
async def admin_menu(message: Message) -> None:
    if not await _require_admin(message):
        return
    await message.answer(strings.ADMIN_MENU_TEXT)


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


async def _rotation_command(message: Message, session: AsyncSession, command: CommandObject, model: type) -> None:
    if not await _require_admin(message):
        return

    args = (command.args or "").split()
    if not args:
        queue = await rotation.get_ordered_queue(session, model)
        if not queue:
            await message.answer(strings.ADMIN_ROTATION_EMPTY)
            return
        lines = [strings.ADMIN_ROTATION_HEADER]
        for row in queue:
            user = row.user
            lines.append(strings.ADMIN_ROTATION_LINE.format(position=row.position + 1, name=user.display_name))
        lines.append("")
        lines.append(strings.ADMIN_ROTATION_USAGE)
        await message.answer("\n".join(lines))
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
    await _rotation_command(message, session, command, TrashRotation)


@router.message(Command("cleaning_rotation"))
async def cleaning_rotation(message: Message, session: AsyncSession, command: CommandObject) -> None:
    await _rotation_command(message, session, command, CleaningRotation)


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
