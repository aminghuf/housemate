from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.db.models import AuditLog, CleaningRotation, TrashRotation, User
from bot.services import rotation, settings_store

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_WEEKDAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


async def log_action(session: AsyncSession, admin_id: int, action: str, details: str | None = None) -> None:
    session.add(AuditLog(admin_id=admin_id, action=action, details=details))
    await session.flush()


def parse_time(text: str | None) -> tuple[int, int] | None:
    text = (text or "").strip()
    if not _TIME_RE.match(text):
        return None
    hour, minute = text.split(":")
    return int(hour), int(minute)


def parse_weekday(text: str | None) -> int | None:
    text = (text or "").strip().lower()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        return value if 0 <= value <= 6 else None
    return _WEEKDAY_NAMES.get(text[:3])


async def reorder_rotation(
    session: AsyncSession, model: type, new_order: list[int]
) -> str | None:
    """Reorders the queue to exactly `new_order`. Returns an error message
    string if `new_order` doesn't contain exactly the current queue's user
    ids, else None on success."""
    current = await rotation.get_ordered_queue(session, model)
    current_ids = {row.user_id for row in current}
    if set(new_order) != current_ids or len(new_order) != len(current_ids):
        return strings.ADMIN_ROTATION_MISMATCH
    await rotation.reorder(session, model, new_order)
    return None


async def add_housemate(session: AsyncSession, telegram_id: int, display_name: str) -> User:
    now = dt.datetime.utcnow()
    user = await session.get(User, telegram_id)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            display_name=display_name,
            is_registered=True,
            is_active=True,
            joined_at=now,
            last_membership_check_at=now,
        )
        session.add(user)
    else:
        user.display_name = display_name
        user.is_registered = True
        user.is_active = True
    await session.flush()

    await rotation.append_if_absent(session, TrashRotation, telegram_id)
    await rotation.append_if_absent(session, CleaningRotation, telegram_id)
    return user


async def remove_housemate(session: AsyncSession, telegram_id: int) -> User | None:
    user = await session.get(User, telegram_id)
    if user is None:
        return None
    user.is_active = False
    await rotation.remove_user_keeping_turn(
        session, TrashRotation, settings_store.TRASH_CURRENT_POSITION, telegram_id
    )
    await rotation.remove_user_keeping_turn(
        session, CleaningRotation, settings_store.CLEANING_CURRENT_POSITION, telegram_id
    )
    await session.flush()
    return user


async def reactivate_housemate(session: AsyncSession, telegram_id: int) -> User | None:
    """Undoes a soft-remove: marks them active again and puts them back at
    the end of both rotations."""
    user = await session.get(User, telegram_id)
    if user is None:
        return None
    user.is_active = True
    await rotation.add_user_keeping_turn(
        session, TrashRotation, settings_store.TRASH_CURRENT_POSITION, telegram_id
    )
    await rotation.add_user_keeping_turn(
        session, CleaningRotation, settings_store.CLEANING_CURRENT_POSITION, telegram_id
    )
    await session.flush()
    return user


async def list_housemates(session: AsyncSession) -> list[User]:
    """Everyone who ever registered, active first then by name, so the
    admin panel can show and toggle them."""
    result = await session.execute(select(User).order_by(User.is_active.desc(), User.display_name))
    return list(result.scalars().all())
