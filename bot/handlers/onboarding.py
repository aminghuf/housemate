from __future__ import annotations

import datetime as dt

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import CleaningRotation, TrashRotation, User
from bot.keyboards import main_menu_keyboard
from bot.middlewares.membership import MEMBER_STATUSES
from bot.services import rotation

router = Router(name="onboarding")


async def _is_channel_member(bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(settings.house_channel_id, user_id)
    except TelegramBadRequest:
        return False
    return member.status in MEMBER_STATUSES


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    tg_user = message.from_user
    is_member = await _is_channel_member(message.bot, tg_user.id)

    if not is_member:
        if settings.house_channel_invite_link:
            text = strings.NOT_A_CHANNEL_MEMBER_WITH_LINK.format(
                invite_link=settings.house_channel_invite_link
            )
        else:
            text = strings.NOT_A_CHANNEL_MEMBER
        await message.answer(text)
        return

    now = dt.datetime.utcnow()
    user = await session.get(User, tg_user.id)
    if user is None:
        user = User(
            telegram_id=tg_user.id,
            display_name=tg_user.full_name,
            username=tg_user.username,
            is_registered=True,
            is_active=True,
            joined_at=now,
            last_membership_check_at=now,
        )
        session.add(user)
        await session.flush()
        await rotation.append_if_absent(session, TrashRotation, user.telegram_id)
        await rotation.append_if_absent(session, CleaningRotation, user.telegram_id)
    else:
        user.display_name = tg_user.full_name
        user.username = tg_user.username
        user.is_registered = True
        user.is_active = True
        user.last_membership_check_at = now

    await session.flush()
    await message.answer(
        strings.WELCOME_REGISTERED.format(display_name=user.display_name),
        reply_markup=main_menu_keyboard(tg_user.id),
    )
