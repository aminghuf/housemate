"""Re-verifies channel membership on incoming updates (spec §3).

Registration itself happens in handlers/onboarding.py on /start; this
middleware only gates *already-registered* users, using a cached
last_membership_check_at timestamp so we don't hit getChatMember on every
single message.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import strings
from bot.config import settings
from bot.db.models import User

MEMBER_STATUSES = {"member", "administrator", "creator"}


class MembershipMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = getattr(event, "from_user", None)
        if tg_user is None:
            return await handler(event, data)

        if isinstance(event, Message) and event.text and event.text.startswith("/start"):
            return await handler(event, data)

        session = data["session"]
        user = await session.get(User, tg_user.id)

        if user is None or not user.is_registered or not user.is_active:
            await self._deny(event, strings.PLEASE_START_FIRST)
            return None

        recheck_after = dt.timedelta(hours=settings.membership_recheck_hours)
        needs_check = (
            user.last_membership_check_at is None
            or dt.datetime.utcnow() - user.last_membership_check_at > recheck_after
        )
        if needs_check:
            is_member = await self._is_channel_member(event.bot, tg_user.id)
            user.last_membership_check_at = dt.datetime.utcnow()
            if not is_member:
                user.is_active = False
                await self._deny(event, strings.ACCESS_LOST_NOT_MEMBER)
                return None

        data["user"] = user
        return await handler(event, data)

    @staticmethod
    async def _is_channel_member(bot, user_id: int) -> bool:
        try:
            member = await bot.get_chat_member(settings.house_channel_id, user_id)
        except TelegramBadRequest:
            return False
        return member.status in MEMBER_STATUSES

    @staticmethod
    async def _deny(event: TelegramObject, text: str) -> None:
        if isinstance(event, CallbackQuery):
            await event.answer(text, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(text)
