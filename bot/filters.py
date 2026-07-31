from aiogram.filters import BaseFilter
from aiogram.types import Message

from bot.config import settings


class IsAdmin(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user is not None and message.from_user.id in settings.admin_id_set
