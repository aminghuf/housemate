import pytest

from bot.db.models import TrashRotation
from bot.services import rotation


def test_advance_position_wraps_around():
    assert rotation.advance_position(0, 3) == 1
    assert rotation.advance_position(1, 3) == 2
    assert rotation.advance_position(2, 3) == 0


def test_advance_position_multi_step_wraps_around():
    assert rotation.advance_position(1, 3, step=3) == 1  # +3 in a queue of 3 is a no-op


def test_advance_position_empty_queue_stays_zero():
    assert rotation.advance_position(0, 0) == 0


def test_user_at_wraps_index():
    queue = ["a", "b", "c"]
    assert rotation.user_at(queue, 0) == "a"
    assert rotation.user_at(queue, 2) == "c"
    assert rotation.user_at(queue, 3) == "a"


def test_user_at_empty_queue_returns_none():
    assert rotation.user_at([], 0) is None


@pytest.mark.asyncio
async def test_append_if_absent_assigns_increasing_positions(session, make_user):
    u1, u2, u3 = await make_user(1), await make_user(2), await make_user(3)

    await rotation.append_if_absent(session, TrashRotation, u1.telegram_id)
    await rotation.append_if_absent(session, TrashRotation, u2.telegram_id)
    await rotation.append_if_absent(session, TrashRotation, u3.telegram_id)

    queue = await rotation.get_ordered_queue(session, TrashRotation)
    assert [row.user_id for row in queue] == [1, 2, 3]
    assert [row.position for row in queue] == [0, 1, 2]


@pytest.mark.asyncio
async def test_append_if_absent_is_idempotent(session, make_user):
    u1 = await make_user(1)
    await rotation.append_if_absent(session, TrashRotation, u1.telegram_id)
    await rotation.append_if_absent(session, TrashRotation, u1.telegram_id)

    queue = await rotation.get_ordered_queue(session, TrashRotation)
    assert len(queue) == 1


@pytest.mark.asyncio
async def test_remove_user_repacks_positions(session, make_user):
    u1, u2, u3 = await make_user(1), await make_user(2), await make_user(3)
    for u in (u1, u2, u3):
        await rotation.append_if_absent(session, TrashRotation, u.telegram_id)

    await rotation.remove_user(session, TrashRotation, u2.telegram_id)

    queue = await rotation.get_ordered_queue(session, TrashRotation)
    assert [row.user_id for row in queue] == [1, 3]
    assert [row.position for row in queue] == [0, 1]


@pytest.mark.asyncio
async def test_reorder_sets_new_positions(session, make_user):
    u1, u2, u3 = await make_user(1), await make_user(2), await make_user(3)
    for u in (u1, u2, u3):
        await rotation.append_if_absent(session, TrashRotation, u.telegram_id)

    await rotation.reorder(session, TrashRotation, [3, 1, 2])

    queue = await rotation.get_ordered_queue(session, TrashRotation)
    assert [row.user_id for row in queue] == [3, 1, 2]
