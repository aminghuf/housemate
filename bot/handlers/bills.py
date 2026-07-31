from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.db.models import User
from bot.services import bills as bills_service
from bot.services.money import format_cents, parse_amount_to_cents
from bot.utils import pagination_keyboard

router = Router(name="bills")


class BillCreation(StatesGroup):
    title = State()
    description = State()
    amount = State()
    confirm = State()


def _bills_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=strings.BILLS_MENU_NEW, callback_data="bills_menu:new")],
            [InlineKeyboardButton(text=strings.BILLS_MENU_MINE, callback_data="bills_menu:mine")],
            [InlineKeyboardButton(text=strings.BILLS_MENU_HISTORY, callback_data="bills_menu:history")],
            [InlineKeyboardButton(text=strings.BILLS_MENU_BALANCE, callback_data="bills_menu:balance")],
        ]
    )


@router.message(F.text == strings.MENU_BILLS)
async def bills_menu(message: Message) -> None:
    await message.answer(strings.MENU_BILLS, reply_markup=_bills_menu_keyboard())


@router.message(Command("new_bill"), StateFilter(None))
@router.callback_query(F.data == "bills_menu:new")
async def start_new_bill(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BillCreation.title)
    if isinstance(event, CallbackQuery):
        await event.answer()
        await event.message.answer(strings.BILL_ASK_TITLE)
    else:
        await event.answer(strings.BILL_ASK_TITLE)


@router.message(BillCreation.title)
async def process_title(message: Message, state: FSMContext) -> None:
    title = (message.text or "").strip()
    if not title:
        await message.answer(strings.BILL_ASK_TITLE)
        return
    await state.update_data(title=title)
    await state.set_state(BillCreation.description)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=strings.BILL_SKIP, callback_data="bill_skip_desc")]])
    await message.answer(strings.BILL_ASK_DESCRIPTION, reply_markup=kb)


@router.callback_query(BillCreation.description, F.data == "bill_skip_desc")
async def skip_description(query: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(description=None)
    await state.set_state(BillCreation.amount)
    await query.answer()
    await query.message.answer(strings.BILL_ASK_AMOUNT)


@router.message(BillCreation.description)
async def process_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=(message.text or "").strip() or None)
    await state.set_state(BillCreation.amount)
    await message.answer(strings.BILL_ASK_AMOUNT)


@router.message(BillCreation.amount)
async def process_amount(message: Message, state: FSMContext, session: AsyncSession) -> None:
    cents = parse_amount_to_cents(message.text or "")
    if cents is None:
        await message.answer(strings.BILL_INVALID_AMOUNT)
        return

    await state.update_data(total_cents=cents)
    await state.set_state(BillCreation.confirm)

    data = await state.get_data()
    active_ids = await bills_service.get_active_user_ids(session, message.from_user.id)
    per_person_preview = cents // len(active_ids)
    description_line = f"{data['description']}\n" if data.get("description") else ""

    text = strings.BILL_CONFIRM.format(
        title=data["title"],
        description_line=description_line,
        total=format_cents(cents),
        per_person=format_cents(per_person_preview),
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=strings.CONFIRM_YES, callback_data="bill_confirm:yes"),
                InlineKeyboardButton(text=strings.CONFIRM_CANCEL, callback_data="bill_confirm:no"),
            ]
        ]
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(BillCreation.confirm, F.data.startswith("bill_confirm:"))
async def confirm_bill(query: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    action = query.data.split(":")[1]
    if action == "no":
        await state.clear()
        await query.answer()
        await query.message.answer(strings.BILL_CANCELLED)
        return

    data = await state.get_data()
    bill = await bills_service.create_bill(
        session,
        title=data["title"],
        description=data.get("description"),
        total_cents=data["total_cents"],
        creator_id=query.from_user.id,
    )
    await bills_service.post_bill(query.bot, session, bill)
    await state.clear()
    await query.answer()
    await query.message.answer(strings.BILL_CREATED)


@router.callback_query(bills_service.BillCB.filter())
async def cb_bill_toggle(query: CallbackQuery, callback_data: bills_service.BillCB, session: AsyncSession) -> None:
    ok, error = await bills_service.toggle_paid(
        session, query.bot, callback_data.bill_id, callback_data.user_id, query.from_user.id
    )
    await query.answer(strings.DONE_BUTTON_TOAST if ok else error, show_alert=not ok)


@router.message(Command("my_bills"))
@router.callback_query(F.data == "bills_menu:mine")
async def my_bills(event: Message | CallbackQuery, session: AsyncSession) -> None:
    user_id = event.from_user.id
    rows = await bills_service.get_unpaid_shares_for_user(session, user_id)

    target = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()

    if not rows:
        await target.answer(strings.NOTHING_TO_SHOW)
        return

    lines = [strings.BILL_MY_BILLS_HEADER]
    for share, bill in rows:
        lines.append(f"#{bill.id} {bill.title} — {format_cents(share.amount_cents)}")
    await target.answer("\n".join(lines))


async def _render_history_page(session: AsyncSession, page: int):
    bills, has_next = await bills_service.get_bills_history_page(session, page)
    if not bills and page == 0:
        return strings.NOTHING_TO_SHOW, None
    lines = []
    for bill in bills:
        settled = await bills_service.is_bill_settled(session, bill.id)
        status = strings.BILL_STATUS_SETTLED if settled else strings.BILL_STATUS_OPEN
        lines.append(
            strings.BILL_HISTORY_ENTRY.format(
                id=bill.id, title=bill.title, total=format_cents(bill.total_amount_cents), status=status
            )
        )
    text = "\n".join(lines) if lines else strings.NOTHING_TO_SHOW
    keyboard = pagination_keyboard("bills_hist", page, has_next)
    return text, keyboard


@router.message(Command("bills_history"))
async def bills_history(message: Message, session: AsyncSession) -> None:
    text, keyboard = await _render_history_page(session, 0)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "bills_menu:history")
async def bills_history_from_menu(query: CallbackQuery, session: AsyncSession) -> None:
    text, keyboard = await _render_history_page(session, 0)
    await query.answer()
    await query.message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data.startswith("bills_hist:"))
async def bills_history_page(query: CallbackQuery, session: AsyncSession) -> None:
    page = int(query.data.split(":")[1])
    text, keyboard = await _render_history_page(session, page)
    await query.message.edit_text(text, reply_markup=keyboard)
    await query.answer()


@router.message(Command("balance"))
@router.callback_query(F.data == "bills_menu:balance")
async def balance(event: Message | CallbackQuery, session: AsyncSession) -> None:
    balances = await bills_service.get_balances(session)

    target = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.answer()

    if not balances:
        await target.answer(strings.BALANCE_NONE_OWED)
        return

    result = await session.execute(select(User).where(User.telegram_id.in_(balances.keys())))
    users = {u.telegram_id: u.display_name for u in result.scalars().all()}

    lines = [strings.BALANCE_HEADER]
    for uid, cents in balances.items():
        lines.append(strings.BALANCE_LINE.format(name=users.get(uid, str(uid)), amount=format_cents(cents)))
    await target.answer("\n".join(lines))
