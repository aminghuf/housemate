import datetime as dt

import pytest

from bot import strings
from bot.db.models import CleaningLog, CleaningRotation, TrashLog, TrashRotation
from bot.services import cleaning as cleaning_service
from bot.services import rotation, settings_store
from bot.services import trash as trash_service

# Same anchor used in test_trash_schedule.py: Tuesday 2026-06-02 -> Carta e Cartone.
ANCHOR = dt.date(2026, 6, 2)


async def _seed_trash_queue(session, make_user, user_ids):
    users = [await make_user(uid) for uid in user_ids]
    for u in users:
        await rotation.append_if_absent(session, TrashRotation, u.telegram_id)
    await settings_store.set_setting(session, settings_store.TRASH_ALTERNATION_ANCHOR_DATE, ANCHOR.isoformat())
    return users


@pytest.mark.asyncio
async def test_trash_handle_done_allows_volunteer_and_records_it(session, make_user, fake_bot):
    u1, u2 = await make_user(1), await make_user(2)
    await rotation.append_if_absent(session, TrashRotation, u1.telegram_id)
    await rotation.append_if_absent(session, TrashRotation, u2.telegram_id)

    log = TrashLog(date=dt.date.today(), trash_type="Umido", assigned_user_id=u1.telegram_id, status="pending", message_id=1)
    session.add(log)
    await session.flush()

    ok, error = await trash_service.handle_done(session, fake_bot, log.id, u2.telegram_id)

    assert ok is True
    assert error == ""
    await session.refresh(log)
    assert log.status == "done"
    assert log.assigned_user_id == u1.telegram_id
    assert log.completed_by_user_id == u2.telegram_id
    # the rotation still advances past the assignee's turn, regardless of who covered it
    position = await settings_store.get_int(session, settings_store.TRASH_CURRENT_POSITION, 0)
    assert position == 1
    assert "User 2" in fake_bot.edited[-1]["text"]


@pytest.mark.asyncio
async def test_trash_handle_skip_still_requires_the_assigned_user(session, make_user, fake_bot):
    u1, u2 = await make_user(1), await make_user(2)
    log = TrashLog(date=dt.date.today(), trash_type="Umido", assigned_user_id=u1.telegram_id, status="pending", message_id=1)
    session.add(log)
    await session.flush()

    ok, error = await trash_service.handle_skip(session, fake_bot, log.id, u2.telegram_id)

    assert ok is False
    assert error == strings.NOT_YOUR_TURN
    await session.refresh(log)
    assert log.status == "pending"


@pytest.mark.asyncio
async def test_cleaning_done_allows_volunteer_and_records_it(session, make_user, fake_bot):
    u1, u2 = await make_user(1), await make_user(2)
    log = CleaningLog(
        week_start_date=dt.date.today(),
        user_id=u1.telegram_id,
        section=cleaning_service.KITCHEN,
        status="pending",
        message_id=1,
    )
    session.add(log)
    await session.flush()

    ok, error = await cleaning_service.handle_response(session, fake_bot, log.id, "done", u2.telegram_id)

    assert ok is True
    await session.refresh(log)
    assert log.status == "done"
    assert log.user_id == u1.telegram_id
    assert log.completed_by_user_id == u2.telegram_id


@pytest.mark.asyncio
async def test_cleaning_skip_still_requires_the_assigned_user(session, make_user, fake_bot):
    u1, u2 = await make_user(1), await make_user(2)
    log = CleaningLog(
        week_start_date=dt.date.today(),
        user_id=u1.telegram_id,
        section=cleaning_service.KITCHEN,
        status="pending",
        message_id=1,
    )
    session.add(log)
    await session.flush()

    ok, error = await cleaning_service.handle_response(session, fake_bot, log.id, "skip", u2.telegram_id)

    assert ok is False
    assert error == strings.NOT_YOUR_TURN
    await session.refresh(log)
    assert log.status == "pending"


@pytest.mark.asyncio
async def test_trash_forecast_projects_across_a_week(session, make_user):
    await _seed_trash_queue(session, make_user, [1, 2, 3])

    # 2026-06-01 (Mon) .. 2026-06-07 (Sun): 6 collection days, Sunday has none.
    entries = await trash_service.get_forecast(session, days=7, start_date=dt.date(2026, 6, 1))

    collection_entries = [e for e in entries if e.trash_type is not None]
    assert len(collection_entries) == 6
    assert all(e.is_projected for e in collection_entries)
    # queue [1,2,3] at position 0, advancing by 1 per projected collection day
    assert [e.user.telegram_id for e in collection_entries] == [1, 2, 3, 1, 2, 3]

    sunday_entry = next(e for e in entries if e.date == dt.date(2026, 6, 7))
    assert sunday_entry.trash_type is None


@pytest.mark.asyncio
async def test_trash_forecast_uses_existing_log_authoritatively(session, make_user):
    await _seed_trash_queue(session, make_user, [1, 2, 3])

    # Monday 2026-06-01 already resolved as done by user 2 (a volunteer,
    # not the queue's position-0 user) — position was already advanced to 1.
    log = TrashLog(
        date=dt.date(2026, 6, 1), trash_type="Umido", assigned_user_id=1, completed_by_user_id=2, status="done", message_id=1
    )
    session.add(log)
    await settings_store.set_setting(session, settings_store.TRASH_CURRENT_POSITION, "1")
    await session.flush()

    entries = await trash_service.get_forecast(session, days=7, start_date=dt.date(2026, 6, 1))

    monday = next(e for e in entries if e.date == dt.date(2026, 6, 1))
    assert monday.is_projected is False
    assert monday.user.telegram_id == 1  # shows the assigned user, matching the real log

    tuesday = next(e for e in entries if e.date == dt.date(2026, 6, 2))
    assert tuesday.is_projected is True
    assert tuesday.user.telegram_id == 2  # position already advanced past Monday


@pytest.mark.asyncio
async def test_trash_forecast_with_no_housemates(session):
    entries = await trash_service.get_forecast(session, days=7, start_date=dt.date(2026, 6, 1))
    collection_entries = [e for e in entries if e.trash_type is not None]
    assert all(e.user is None for e in collection_entries)


@pytest.mark.asyncio
async def test_next_week_assignments_projects_upcoming_sunday(session, make_user):
    users = [await make_user(uid) for uid in (1, 2, 3)]
    for u in users:
        await rotation.append_if_absent(session, CleaningRotation, u.telegram_id)

    # Monday 2026-07-27 -> upcoming cleaning Sunday is 2026-08-02.
    entry = await cleaning_service.get_next_week_assignments(session, today=dt.date(2026, 7, 27))

    assert entry.date == dt.date(2026, 8, 2)
    assert entry.is_projected is True
    assert entry.assignments[cleaning_service.KITCHEN][0].telegram_id == 1
    assert entry.assignments[cleaning_service.HALL][0].telegram_id == 2
    assert entry.assignments[cleaning_service.BATHROOM][0].telegram_id == 3


@pytest.mark.asyncio
async def test_next_week_assignments_looks_past_the_posted_week(session, make_user, fake_bot):
    users = [await make_user(uid) for uid in (1, 2, 3)]
    for u in users:
        await rotation.append_if_absent(session, CleaningRotation, u.telegram_id)

    # Saturday: this week's assignments get posted for Sunday 2026-08-02.
    await cleaning_service.create_weekly_assignments_and_post(session=session, bot=fake_bot, today=dt.date(2026, 8, 1))

    entry = await cleaning_service.get_next_week_assignments(session, today=dt.date(2026, 8, 1))

    # "next week" must be the Sunday *after* the one just announced.
    assert entry.date == dt.date(2026, 8, 9)
    assert entry.is_projected is True
    # ...and with 3 housemates it must not repeat this week's trio.
    assert entry.assignments[cleaning_service.KITCHEN][0].telegram_id == 2
