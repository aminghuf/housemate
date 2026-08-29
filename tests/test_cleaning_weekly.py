"""Weekly cleaning rollover: rotation advancement, stale-week close-out,
and the daily nag for sections nobody ticked off."""
import datetime as dt

import pytest

from bot.db.models import CleaningLog, CleaningRotation
from bot.services import cleaning as cleaning_service
from bot.services import rotation, settings_store

SUNDAY = dt.date(2026, 8, 2)
SATURDAY_BEFORE = dt.date(2026, 8, 1)
NEXT_SATURDAY = dt.date(2026, 8, 8)
NEXT_SUNDAY = dt.date(2026, 8, 9)


async def _seed(session, make_user, count):
    users = [await make_user(i + 1) for i in range(count)]
    for u in users:
        await rotation.append_if_absent(session, CleaningRotation, u.telegram_id)
    return users


@pytest.mark.parametrize(
    "queue_length,expected",
    [(1, 1), (2, 3), (3, 1), (4, 3), (5, 3), (6, 3)],
)
def test_weekly_rotation_step_never_lands_back_on_itself(queue_length, expected):
    step = cleaning_service.weekly_rotation_step(queue_length)
    assert step == expected
    if queue_length > 1:
        # The whole point: advancing must actually move the position.
        assert (0 + step) % queue_length != 0


def test_weekly_rotation_step_handles_empty_queue():
    assert cleaning_service.weekly_rotation_step(0) == 0


@pytest.mark.asyncio
async def test_three_housemates_rotate_sections_week_over_week(session, make_user, fake_bot):
    """Regression: with exactly 3 housemates the old step of 3 made
    `(pos + 3) % 3 == pos`, freezing assignments so everyone kept the same
    section forever and every new week looked identical to the last."""
    await _seed(session, make_user, 3)

    week_one = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    week_two = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=NEXT_SATURDAY
    )

    by_section_one = {log.section: log.user_id for log in week_one}
    by_section_two = {log.section: log.user_id for log in week_two}

    assert by_section_one == {"kitchen": 1, "hall": 2, "bathroom": 3}
    assert by_section_two == {"kitchen": 2, "hall": 3, "bathroom": 1}
    assert by_section_one != by_section_two


@pytest.mark.asyncio
async def test_rotation_advances_even_when_nobody_responded(session, make_user, fake_bot):
    await _seed(session, make_user, 3)
    await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    # Deliberately leave every section pending.
    week_two = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=NEXT_SATURDAY
    )
    assert {log.section: log.user_id for log in week_two} == {"kitchen": 2, "hall": 3, "bathroom": 1}


@pytest.mark.asyncio
async def test_unanswered_week_is_closed_out_as_missed(session, make_user, fake_bot):
    await _seed(session, make_user, 3)
    week_one = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    # One section gets done; the other two are ignored.
    await cleaning_service.handle_response(session, fake_bot, week_one[0].id, "done", 1)

    await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=NEXT_SATURDAY
    )

    for log in week_one:
        await session.refresh(log)
    statuses = {log.section: log.status for log in week_one}
    assert statuses["kitchen"] == "done"
    assert statuses["hall"] == cleaning_service.MISSED
    assert statuses["bathroom"] == cleaning_service.MISSED


@pytest.mark.asyncio
async def test_posting_twice_for_the_same_week_is_a_no_op(session, make_user, fake_bot):
    await _seed(session, make_user, 3)
    first = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    position_after_first = await settings_store.get_int(
        session, settings_store.CLEANING_CURRENT_POSITION, 0
    )

    # Same cleaning week (Saturday and its Sunday both map to 2026-08-02).
    again = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SUNDAY
    )

    assert first != []
    assert again == []
    assert len(fake_bot.sent) == 1
    assert await settings_store.get_int(session, settings_store.CLEANING_CURRENT_POSITION, 0) == position_after_first


@pytest.mark.asyncio
async def test_nag_skips_a_week_that_has_not_arrived_yet(session, make_user, fake_bot):
    await _seed(session, make_user, 3)
    await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    fake_bot.sent.clear()

    # Saturday evening: assignments are for tomorrow, so nothing to chase yet.
    posted = await cleaning_service.post_pending_nag(fake_bot, session, today=SATURDAY_BEFORE)

    assert posted is False
    assert fake_bot.sent == []


@pytest.mark.asyncio
async def test_nag_lists_only_the_sections_still_pending(session, make_user, fake_bot):
    await _seed(session, make_user, 3)
    logs = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    await cleaning_service.handle_response(session, fake_bot, logs[0].id, "done", 1)
    fake_bot.sent.clear()

    posted = await cleaning_service.post_pending_nag(fake_bot, session, today=SUNDAY)

    assert posted is True
    assert len(fake_bot.sent) == 1
    text = fake_bot.sent[0]["text"]
    # Kitchen was done, so only hall and bathroom should be chased.
    assert "آشپزخانه" not in text
    assert "هال" in text
    assert "حمام" in text
    # Threaded onto the original assignment post so its buttons stay reachable.
    assert fake_bot.sent[0]["reply_to_message_id"] == logs[0].message_id


@pytest.mark.asyncio
async def test_nag_goes_quiet_once_everything_is_handled(session, make_user, fake_bot):
    await _seed(session, make_user, 3)
    logs = await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    for log in logs:
        await cleaning_service.handle_response(session, fake_bot, log.id, "done", log.user_id)
    fake_bot.sent.clear()

    assert await cleaning_service.post_pending_nag(fake_bot, session, today=SUNDAY) is False
    assert fake_bot.sent == []


@pytest.mark.asyncio
async def test_nag_stops_chasing_a_week_that_already_rolled_over(session, make_user, fake_bot):
    await _seed(session, make_user, 3)
    await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=SATURDAY_BEFORE
    )
    # New week starts, retiring the old pending sections as `missed`.
    await cleaning_service.create_weekly_assignments_and_post(
        session=session, bot=fake_bot, today=NEXT_SATURDAY
    )

    pending = await cleaning_service.get_pending_logs_for_nag(session, today=NEXT_SUNDAY)

    assert {log.week_start_date for log in pending} == {NEXT_SUNDAY}


@pytest.mark.asyncio
async def test_nag_is_silent_when_no_assignments_exist(session, fake_bot):
    assert await cleaning_service.post_pending_nag(fake_bot, session, today=SUNDAY) is False
