from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.db.models import User
from bot.services import shopping as shopping_service
from bot.utils import pagination_keyboard

router = Router(name="shopping")


class ShoppingAdd(StatesGroup):
    title = State()


async def _dm_view(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    """The current list rendered for a DM: same items and tick buttons as the
    pinned channel message, plus an "add item" button underneath."""
    text, keyboard = await shopping_service.render_current_list(session)
    rows = list(keyboard.inline_keyboard) if keyboard else []
    if keyboard is not None:
        text = f"{text}\n\n{strings.SHOPPING_DM_LIST_HINT}"
    rows.append([InlineKeyboardButton(text=strings.SHOPPING_ADD_BUTTON, callback_data="shopping_menu:add")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == strings.MENU_SHOPPING)
async def shopping_menu(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _dm_view(session)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("add_item"), StateFilter(None))
@router.callback_query(F.data == "shopping_menu:add")
async def start_add_item(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ShoppingAdd.title)
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(strings.SHOPPING_ASK_TITLE)
    else:
        await event.answer(strings.SHOPPING_ASK_TITLE)


@router.message(ShoppingAdd.title)
async def process_add_item(message: Message, state: FSMContext, session: AsyncSession) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer(strings.SHOPPING_ASK_TITLE)
        return
    await shopping_service.add_item(session, message.bot, title, message.from_user.id)
    await state.clear()
    await message.answer(strings.SHOPPING_ITEM_ADDED.format(title=title))

    # Show the updated list straight away so the DM reflects the addition.
    text, keyboard = await _dm_view(session)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(shopping_service.ShoppingCB.filter())
async def cb_purchase(query: CallbackQuery, callback_data: shopping_service.ShoppingCB, session: AsyncSession) -> None:
    ok, error = await shopping_service.mark_purchased(session, query.bot, callback_data.item_id, query.from_user.id)
    await query.answer(strings.DONE_BUTTON_TOAST if ok else error, show_alert=not ok)

    # mark_purchased refreshes the pinned channel message; when the tap came
    # from a DM that copy needs refreshing too, or it keeps showing the item.
    if ok and query.message is not None and query.message.chat.type == "private":
        text, keyboard = await _dm_view(session)
        try:
            await query.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest:
            pass


async def _render_history_page(session: AsyncSession, page: int):
    items, has_next = await shopping_service.get_history_page(session, page)
    if not items and page == 0:
        return strings.NOTHING_TO_SHOW, None
    lines = []
    for item in items:
        buyer = await session.get(User, item.purchased_by)
        lines.append(
            strings.SHOPPING_HISTORY_ENTRY.format(
                title=item.title,
                buyer=buyer.display_name if buyer else str(item.purchased_by),
                date=item.purchased_at.date().isoformat(),
            )
        )
    text = "\n".join(lines) if lines else strings.NOTHING_TO_SHOW
    keyboard = pagination_keyboard("shop_hist", page, has_next)
    return text, keyboard


@router.message(Command("shopping_history"))
async def shopping_history(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _render_history_page(session, 0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("shop_hist:"))
async def shopping_history_page(query: CallbackQuery, session: AsyncSession) -> None:
    page = int(query.data.split(":")[1])
    text, keyboard = await _render_history_page(session, page)
    await query.message.edit_text(text, reply_markup=keyboard)
    await query.answer()
