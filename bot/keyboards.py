from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot import strings
from bot.config import settings


def main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=strings.MENU_TRASH), KeyboardButton(text=strings.MENU_CLEANING)],
        [KeyboardButton(text=strings.MENU_BILLS), KeyboardButton(text=strings.MENU_SHOPPING)],
    ]
    if user_id in settings.admin_id_set:
        rows.append([KeyboardButton(text=strings.MENU_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
