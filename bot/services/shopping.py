from __future__ import annotations

import datetime as dt

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import ShoppingItem, ShoppingListMessage


class ShoppingCB(CallbackData, prefix="shop"):
    item_id: int


def _render(items: list[ShoppingItem]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not items:
        return strings.SHOPPING_LIST_EMPTY, None

    lines = [strings.SHOPPING_LIST_HEADER] + [f"• {item.title}" for item in items]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ {item.title}", callback_data=ShoppingCB(item_id=item.id).pack())]
            for item in items
        ]
    )
    return "\n".join(lines), keyboard


async def _get_open_items(session: AsyncSession) -> list[ShoppingItem]:
    result = await session.execute(
        select(ShoppingItem).where(ShoppingItem.purchased == False).order_by(ShoppingItem.added_at)  # noqa: E712
    )
    return list(result.scalars().all())


async def sync_channel_message(bot: Bot, session: AsyncSession) -> None:
    """Renders the current list into the single pinned channel message,
    editing it in place so the pin slot stays stable (spec §7)."""
    items = await _get_open_items(session)
    text, keyboard = _render(items)

    singleton = await session.get(ShoppingListMessage, 1)

    if singleton is not None and singleton.channel_message_id is not None:
        try:
            await bot.edit_message_text(
                chat_id=settings.house_channel_id,
                message_id=singleton.channel_message_id,
                text=text,
                reply_markup=keyboard,
            )
            singleton.updated_at = dt.datetime.utcnow()
            await session.flush()
            return
        except TelegramBadRequest:
            pass  # message was deleted/unpinnable out-of-band; recreate below

    message = await bot.send_message(settings.house_channel_id, text, reply_markup=keyboard)
    if singleton is None:
        singleton = ShoppingListMessage(id=1, channel_message_id=message.message_id)
        session.add(singleton)
    else:
        singleton.channel_message_id = message.message_id
        singleton.updated_at = dt.datetime.utcnow()
    await session.flush()

    try:
        await bot.pin_chat_message(settings.house_channel_id, message.message_id, disable_notification=True)
    except TelegramBadRequest:
        pass


async def add_item(session: AsyncSession, bot: Bot, title: str, added_by: int) -> ShoppingItem:
    item = ShoppingItem(title=title, added_by=added_by)
    session.add(item)
    await session.flush()
    await sync_channel_message(bot, session)
    return item


async def mark_purchased(session: AsyncSession, bot: Bot, item_id: int, acting_user_id: int) -> tuple[bool, str]:
    item = await session.get(ShoppingItem, item_id)
    if item is None or item.purchased:
        return False, strings.ALREADY_HANDLED

    item.purchased = True
    item.purchased_by = acting_user_id
    item.purchased_at = dt.datetime.utcnow()
    await session.flush()
    await sync_channel_message(bot, session)
    return True, ""


async def get_history_page(session: AsyncSession, page: int, page_size: int = 5) -> tuple[list[ShoppingItem], bool]:
    result = await session.execute(
        select(ShoppingItem)
        .where(ShoppingItem.purchased == True)  # noqa: E712
        .order_by(ShoppingItem.purchased_at.desc())
        .offset(page * page_size)
        .limit(page_size + 1)
    )
    rows = list(result.scalars().all())
    has_next = len(rows) > page_size
    return rows[:page_size], has_next
