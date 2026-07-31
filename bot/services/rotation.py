"""Generic round-robin queue helpers shared by trash duty and cleaning turns.

Both `TrashRotation` and `CleaningRotation` share the same (id, position,
user_id) shape, so the queue manipulation logic (append/remove/reorder) is
written once here and reused by both services.
"""
from __future__ import annotations

from typing import Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import CleaningRotation, TrashRotation

RotationModel = TypeVar("RotationModel", TrashRotation, CleaningRotation)


async def get_ordered_queue(session: AsyncSession, model: type[RotationModel]) -> list[RotationModel]:
    result = await session.execute(select(model).order_by(model.position))
    return list(result.scalars().all())


async def append_if_absent(session: AsyncSession, model: type[RotationModel], user_id: int) -> None:
    existing = await session.execute(select(model).where(model.user_id == user_id))
    if existing.scalar_one_or_none() is not None:
        return
    max_pos = (await session.execute(select(func.max(model.position)))).scalar()
    next_pos = 0 if max_pos is None else max_pos + 1
    session.add(model(position=next_pos, user_id=user_id))
    await session.flush()


async def remove_user(session: AsyncSession, model: type[RotationModel], user_id: int) -> None:
    queue = await get_ordered_queue(session, model)
    remaining_user_ids = [row.user_id for row in queue if row.user_id != user_id]
    for row in queue:
        if row.user_id == user_id:
            await session.delete(row)
    await session.flush()
    for idx, uid in enumerate(remaining_user_ids):
        row = (await session.execute(select(model).where(model.user_id == uid))).scalar_one()
        row.position = idx
    await session.flush()


async def reorder(session: AsyncSession, model: type[RotationModel], ordered_user_ids: Sequence[int]) -> None:
    queue = await get_ordered_queue(session, model)
    by_user = {row.user_id: row for row in queue}

    # Two-phase update: jump through unique negative positions first, since
    # writing final positions directly can collide with another row's
    # current position (position has a UNIQUE constraint) mid-update.
    for row in queue:
        row.position = -(row.position + 1)
    await session.flush()

    for idx, uid in enumerate(ordered_user_ids):
        by_user[uid].position = idx
    await session.flush()


def advance_position(current_position: int, queue_length: int, step: int = 1) -> int:
    """Pure helper: next position in a circular queue of the given length."""
    if queue_length == 0:
        return 0
    return (current_position + step) % queue_length


def user_at(queue: Sequence[RotationModel], position: int) -> RotationModel | None:
    if not queue:
        return None
    return queue[position % len(queue)]
