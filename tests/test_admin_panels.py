"""Admin panels: housemate activation and button-driven rotation editing.

The important property under test is that editing a queue never silently
moves the current turn onto a different person.
"""
import re

import pytest

from bot.db.models import CleaningRotation, TrashRotation, User
from bot.handlers import admin_ui
from bot.services import admin as admin_service
from bot.services import rotation, settings_store

POS = settings_store.TRASH_CURRENT_POSITION


async def _queue_ids(session, model=TrashRotation):
    return [row.user_id for row in await rotation.get_ordered_queue(session, model)]


async def _seed(session, make_user, count=3):
    users = [await make_user(i + 1) for i in range(count)]
    for u in users:
        await rotation.append_if_absent(session, TrashRotation, u.telegram_id)
    return users


@pytest.mark.asyncio
async def test_move_user_up_and_down(session, make_user):
    await _seed(session, make_user)

    assert await rotation.move_user(session, TrashRotation, POS, 3, -1) is True
    assert await _queue_ids(session) == [1, 3, 2]

    assert await rotation.move_user(session, TrashRotation, POS, 3, 1) is True
    assert await _queue_ids(session) == [1, 2, 3]


@pytest.mark.asyncio
async def test_move_user_refuses_to_run_off_the_ends(session, make_user):
    await _seed(session, make_user)

    assert await rotation.move_user(session, TrashRotation, POS, 1, -1) is False
    assert await rotation.move_user(session, TrashRotation, POS, 3, 1) is False
    assert await _queue_ids(session) == [1, 2, 3]


@pytest.mark.asyncio
async def test_move_user_ignores_someone_not_in_the_queue(session, make_user):
    await _seed(session, make_user)
    await make_user(99)
    assert await rotation.move_user(session, TrashRotation, POS, 99, -1) is False


@pytest.mark.asyncio
async def test_reordering_keeps_the_same_person_on_duty(session, make_user):
    await _seed(session, make_user)
    # User 2 is on duty.
    await settings_store.set_setting(session, POS, "1")

    # Move them to the front; the turn must follow the person, not the slot.
    await rotation.move_user(session, TrashRotation, POS, 2, -1)

    assert await _queue_ids(session) == [2, 1, 3]
    assert await settings_store.get_int(session, POS, 0) == 0


@pytest.mark.asyncio
async def test_moving_someone_else_does_not_steal_the_turn(session, make_user):
    await _seed(session, make_user)
    await settings_store.set_setting(session, POS, "0")  # user 1 on duty

    await rotation.move_user(session, TrashRotation, POS, 3, -1)  # shuffle behind them

    queue = await _queue_ids(session)
    position = await settings_store.get_int(session, POS, 0)
    assert queue[position] == 1


@pytest.mark.asyncio
async def test_removing_the_person_on_duty_passes_the_turn_onward(session, make_user):
    await _seed(session, make_user)
    await settings_store.set_setting(session, POS, "1")  # user 2 on duty

    await rotation.remove_user_keeping_turn(session, TrashRotation, POS, 2)

    queue = await _queue_ids(session)
    position = await settings_store.get_int(session, POS, 0)
    assert queue == [1, 3]
    assert queue[position] == 3  # duty went to whoever was next, not back to 1


@pytest.mark.asyncio
async def test_removing_someone_else_keeps_the_turn_put(session, make_user):
    await _seed(session, make_user)
    await settings_store.set_setting(session, POS, "2")  # user 3 on duty

    await rotation.remove_user_keeping_turn(session, TrashRotation, POS, 1)

    queue = await _queue_ids(session)
    position = await settings_store.get_int(session, POS, 0)
    assert queue[position] == 3


@pytest.mark.asyncio
async def test_removing_the_last_person_resets_the_position(session, make_user):
    await _seed(session, make_user, count=1)
    await rotation.remove_user_keeping_turn(session, TrashRotation, POS, 1)

    assert await _queue_ids(session) == []
    assert await settings_store.get_int(session, POS, 0) == 0


@pytest.mark.asyncio
async def test_adding_someone_back_does_not_disturb_the_turn(session, make_user):
    await _seed(session, make_user)
    await settings_store.set_setting(session, POS, "1")  # user 2 on duty
    await make_user(4)

    await rotation.add_user_keeping_turn(session, TrashRotation, POS, 4)

    queue = await _queue_ids(session)
    position = await settings_store.get_int(session, POS, 0)
    assert queue == [1, 2, 3, 4]
    assert queue[position] == 2


@pytest.mark.asyncio
async def test_deactivating_a_housemate_drops_them_from_both_rotations(session, make_user):
    users = [await make_user(i + 1) for i in range(3)]
    for u in users:
        await rotation.append_if_absent(session, TrashRotation, u.telegram_id)
        await rotation.append_if_absent(session, CleaningRotation, u.telegram_id)

    await admin_service.remove_housemate(session, 2)

    assert await _queue_ids(session, TrashRotation) == [1, 3]
    assert await _queue_ids(session, CleaningRotation) == [1, 3]
    assert (await session.get(User, 2)).is_active is False


@pytest.mark.asyncio
async def test_reactivating_a_housemate_restores_them_to_both_rotations(session, make_user):
    users = [await make_user(i + 1) for i in range(3)]
    for u in users:
        await rotation.append_if_absent(session, TrashRotation, u.telegram_id)
        await rotation.append_if_absent(session, CleaningRotation, u.telegram_id)
    await admin_service.remove_housemate(session, 2)

    await admin_service.reactivate_housemate(session, 2)

    assert (await session.get(User, 2)).is_active is True
    assert set(await _queue_ids(session, TrashRotation)) == {1, 2, 3}
    assert set(await _queue_ids(session, CleaningRotation)) == {1, 2, 3}


@pytest.mark.asyncio
async def test_list_housemates_puts_active_members_first(session, make_user):
    for i in range(3):
        await make_user(i + 1)
    await admin_service.remove_housemate(session, 1)

    listed = await admin_service.list_housemates(session)

    assert [u.telegram_id for u in listed][-1] == 1
    assert all(u.is_active for u in listed[:-1])


@pytest.mark.asyncio
async def test_housemates_panel_renders_a_toggle_per_person(session, make_user):
    for i in range(3):
        await make_user(i + 1)
    await admin_service.remove_housemate(session, 3)

    text, keyboard = await admin_ui.render_housemates(session)

    labels = [row[0].text for row in keyboard.inline_keyboard]
    assert sum(1 for label in labels if label.startswith("✅")) == 2
    assert sum(1 for label in labels if label.startswith("❌")) == 1
    assert "هم‌خونه‌ای‌ها" in text


@pytest.mark.asyncio
async def test_housemates_panel_handles_an_empty_house(session):
    text, keyboard = await admin_ui.render_housemates(session)
    assert "ثبت‌نام" in text
    # Just the "add manually" and "back" rows.
    assert len(keyboard.inline_keyboard) == 2


@pytest.mark.asyncio
async def test_rotation_panel_marks_whose_turn_it_is(session, make_user):
    await _seed(session, make_user)
    await settings_store.set_setting(session, POS, "1")

    text, keyboard = await admin_ui.render_rotation(session, admin_ui.TRASH)

    # Only the numbered queue rows, not the "👉 = نوبت فعلی" legend.
    entry_lines = [line for line in text.split("\n") if re.match(r"^(👉 )?\d+\. ", line)]
    marked = [line for line in entry_lines if "👉" in line]
    assert len(entry_lines) == 3
    assert len(marked) == 1
    assert "2." in marked[0]
    # Each queue member gets up / label / down / remove.
    assert any(len(row) == 4 for row in keyboard.inline_keyboard)


@pytest.mark.asyncio
async def test_rotation_panel_offers_to_re_add_missing_active_housemates(session, make_user):
    await _seed(session, make_user)
    absent = await make_user(4)  # active, but never added to the trash queue

    _, keyboard = await admin_ui.render_rotation(session, admin_ui.TRASH)

    add_labels = [row[0].text for row in keyboard.inline_keyboard if len(row) == 1 and row[0].text.startswith("➕")]
    assert any(absent.display_name in label for label in add_labels)


@pytest.mark.asyncio
async def test_rotation_panel_survives_an_empty_queue(session):
    text, keyboard = await admin_ui.render_rotation(session, admin_ui.CLEANING)
    assert "خالیه" in text
    assert keyboard.inline_keyboard  # at least the back button
