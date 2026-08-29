"""Shopping list: the DM view of the list, and the per-item channel notice."""
import pytest

from bot.services import shopping as shopping_service


@pytest.mark.asyncio
async def test_empty_list_renders_the_empty_placeholder(session):
    text, keyboard = await shopping_service.render_current_list(session)
    assert "خالیه" in text
    assert keyboard is None


@pytest.mark.asyncio
async def test_open_items_render_with_a_tick_button_each(session, make_user, fake_bot):
    await make_user(1)
    await shopping_service.add_item(session, fake_bot, "شیر", 1)
    await shopping_service.add_item(session, fake_bot, "نان", 1)

    text, keyboard = await shopping_service.render_current_list(session)

    assert "شیر" in text and "نان" in text
    assert keyboard is not None
    assert len(keyboard.inline_keyboard) == 2


@pytest.mark.asyncio
async def test_adding_an_item_announces_it_in_the_channel(session, make_user, fake_bot):
    await make_user(1)
    await shopping_service.add_item(session, fake_bot, "تخم مرغ", 1)

    # One message creates/edits the pinned list, one announces the addition.
    announcements = [m for m in fake_bot.sent if "تخم مرغ" in m["text"] and "اضافه کرد" in m["text"]]
    assert len(announcements) == 1
    assert announcements[0]["parse_mode"] == "HTML"
    assert "User 1" in announcements[0]["text"]


@pytest.mark.asyncio
async def test_channel_announcement_escapes_html_in_the_title(session, make_user, fake_bot):
    await make_user(1)
    await shopping_service.add_item(session, fake_bot, "<b>bold</b>", 1)

    announcement = next(m for m in fake_bot.sent if "اضافه کرد" in m["text"])
    assert "&lt;b&gt;bold&lt;/b&gt;" in announcement["text"]


@pytest.mark.asyncio
async def test_purchased_items_drop_out_of_the_rendered_list(session, make_user, fake_bot):
    await make_user(1)
    item = await shopping_service.add_item(session, fake_bot, "پنیر", 1)

    ok, _ = await shopping_service.mark_purchased(session, fake_bot, item.id, 1)
    text, keyboard = await shopping_service.render_current_list(session)

    assert ok is True
    assert "پنیر" not in text
    assert keyboard is None
