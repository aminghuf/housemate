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
from bot.services import settings_store

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


async def _anchor_user_id(session: AsyncSession, model: type[RotationModel], position_key: str) -> int | None:
    """Whoever the stored position currently points at."""
    queue = await get_ordered_queue(session, model)
    row = user_at(queue, await settings_store.get_int(session, position_key, 0))
    return row.user_id if row else None


async def _restore_anchor(
    session: AsyncSession, model: type[RotationModel], position_key: str, anchor_user_id: int | None
) -> None:
    """Re-points the stored position at `anchor_user_id` after the queue was
    edited, so shuffling the order doesn't silently hand the current turn to
    somebody else. Falls back to clamping when the anchor has left."""
    queue = await get_ordered_queue(session, model)
    if not queue:
        await settings_store.set_setting(session, position_key, "0")
        return
    for idx, row in enumerate(queue):
        if row.user_id == anchor_user_id:
            await settings_store.set_setting(session, position_key, str(idx))
            return
    position = await settings_store.get_int(session, position_key, 0)
    await settings_store.set_setting(session, position_key, str(position % len(queue)))


async def move_user(
    session: AsyncSession, model: type[RotationModel], position_key: str, user_id: int, delta: int
) -> bool:
    """Swaps a person one slot up (-1) or down (+1). Returns False when they
    aren't in the queue or are already at the end they're moving toward."""
    queue = await get_ordered_queue(session, model)
    user_ids = [row.user_id for row in queue]
    if user_id not in user_ids:
        return False

    index = user_ids.index(user_id)
    target = index + delta
    if not 0 <= target < len(user_ids):
        return False

    anchor = await _anchor_user_id(session, model, position_key)
    user_ids[index], user_ids[target] = user_ids[target], user_ids[index]
    await reorder(session, model, user_ids)
    await _restore_anchor(session, model, position_key, anchor)
    return True


async def remove_user_keeping_turn(
    session: AsyncSession, model: type[RotationModel], position_key: str, user_id: int
) -> bool:
    """Drops someone from the queue. If it was their turn, it passes to
    whoever came after them rather than to an arbitrary index."""
    queue = await get_ordered_queue(session, model)
    user_ids = [row.user_id for row in queue]
    if user_id not in user_ids:
        return False

    anchor = await _anchor_user_id(session, model, position_key)
    if anchor == user_id:
        index = user_ids.index(user_id)
        anchor = user_ids[(index + 1) % len(user_ids)] if len(user_ids) > 1 else None

    await remove_user(session, model, user_id)
    await _restore_anchor(session, model, position_key, anchor)
    return True


async def add_user_keeping_turn(
    session: AsyncSession, model: type[RotationModel], position_key: str, user_id: int
) -> None:
    """Appends someone to the end of the queue, leaving the current turn put."""
    anchor = await _anchor_user_id(session, model, position_key)
    await append_if_absent(session, model, user_id)
    await _restore_anchor(session, model, position_key, anchor)


def user_at(queue: Sequence[RotationModel], position: int) -> RotationModel | None:
    if not queue:
        return None
    return queue[position % len(queue)]
