from __future__ import annotations

import datetime as dt
import html
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import settings
from bot.db.models import User

PAGE_SIZE = 5


def mention(user: User) -> str:
    """HTML mention that works even without a public @username."""
    return f'<a href="tg://user?id={user.telegram_id}">{html.escape(user.display_name)}</a>'


def now_local() -> dt.datetime:
    return dt.datetime.now(ZoneInfo(settings.timezone))


def now_str() -> str:
    return now_local().strftime("%Y-%m-%d %H:%M")


def format_dt(value: dt.datetime) -> str:
    """Formats a naive UTC datetime (as stored in the DB) in the configured local timezone."""
    aware = value.replace(tzinfo=dt.timezone.utc).astimezone(ZoneInfo(settings.timezone))
    return aware.strftime("%Y-%m-%d %H:%M")


def pagination_keyboard(prefix: str, page: int, has_next: bool) -> InlineKeyboardMarkup | None:
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"{prefix}:{page - 1}"))
    if has_next:
        buttons.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"{prefix}:{page + 1}"))
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
