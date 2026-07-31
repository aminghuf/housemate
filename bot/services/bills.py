from __future__ import annotations

import datetime as dt
import html

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import Bill, BillShare, User
from bot.services.money import format_cents


class BillCB(CallbackData, prefix="bill"):
    bill_id: int
    user_id: int


def compute_shares_cents(total_cents: int, user_ids: list[int], creator_id: int) -> dict[int, int]:
    """Even split in whole cents; any remainder from integer division goes
    to the bill creator so shares always sum exactly to the total
    (v1 rule, see spec §6 / §13.2)."""
    if not user_ids:
        raise ValueError("no users to split the bill among")
    if creator_id not in user_ids:
        raise ValueError("creator must be one of the users the bill is split among")

    n = len(user_ids)
    base = total_cents // n
    shares = {uid: base for uid in user_ids}
    remainder = total_cents - base * n
    shares[creator_id] += remainder
    return shares


async def get_active_user_ids(session: AsyncSession, creator_id: int) -> list[int]:
    result = await session.execute(select(User.telegram_id).where(User.is_active == True))  # noqa: E712
    ids = list(result.scalars().all())
    if creator_id not in ids:
        ids.append(creator_id)
    return ids


async def create_bill(
    session: AsyncSession, *, title: str, description: str | None, total_cents: int, creator_id: int
) -> Bill:
    active_ids = await get_active_user_ids(session, creator_id)
    shares_cents = compute_shares_cents(total_cents, active_ids, creator_id)
    per_person_cents = total_cents // len(active_ids)

    bill = Bill(
        title=title,
        description=description,
        total_amount_cents=total_cents,
        per_person_amount_cents=per_person_cents,
        created_by=creator_id,
    )
    session.add(bill)
    await session.flush()

    for uid, cents in shares_cents.items():
        session.add(BillShare(bill_id=bill.id, user_id=uid, amount_cents=cents))
    await session.flush()
    return bill


async def get_bill_with_shares(session: AsyncSession, bill_id: int) -> tuple[Bill, list[BillShare]]:
    bill = await session.get(Bill, bill_id)
    result = await session.execute(select(BillShare).where(BillShare.bill_id == bill_id))
    return bill, list(result.scalars().all())


async def _users_by_id(session: AsyncSession, user_ids: list[int]) -> dict[int, User]:
    result = await session.execute(select(User).where(User.telegram_id.in_(user_ids)))
    return {u.telegram_id: u for u in result.scalars().all()}


def render_bill(bill: Bill, shares: list[BillShare], users_by_id: dict[int, User]) -> tuple[str, InlineKeyboardMarkup | None]:
    # Messages are sent with parse_mode="HTML" (for the <b> title), so any
    # user-supplied text going into the body — title, description, names —
    # must be escaped or Telegram's HTML parser can reject the edit/send.
    lines = [strings.BILL_HEADER.format(title=html.escape(bill.title))]
    if bill.description:
        lines.append(html.escape(bill.description))
    lines.append(strings.BILL_TOTAL_LINE.format(total=format_cents(bill.total_amount_cents)))
    lines.append(strings.BILL_PER_PERSON_LINE.format(per_person=format_cents(bill.per_person_amount_cents)))

    all_paid = all(s.paid for s in shares)
    if all_paid:
        lines.append("")
        lines.append(strings.BILL_FULLY_SETTLED)
        for s in shares:
            lines.append(strings.BILL_PAID_LABEL.format(name=html.escape(users_by_id[s.user_id].display_name)))
        return "\n".join(lines), None

    keyboard_rows = []
    for s in shares:
        name = users_by_id[s.user_id].display_name
        label = strings.BILL_PAID_LABEL.format(name=name) if s.paid else strings.BILL_UNPAID_LABEL.format(name=name)
        keyboard_rows.append(
            [InlineKeyboardButton(text=label, callback_data=BillCB(bill_id=bill.id, user_id=s.user_id).pack())]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


async def post_bill(bot: Bot, session: AsyncSession, bill: Bill) -> None:
    bill, shares = await get_bill_with_shares(session, bill.id)
    users_by_id = await _users_by_id(session, [s.user_id for s in shares])
    text, keyboard = render_bill(bill, shares, users_by_id)
    message = await bot.send_message(settings.house_channel_id, text, reply_markup=keyboard, parse_mode="HTML")
    bill.channel_message_id = message.message_id
    await session.flush()


async def toggle_paid(
    session: AsyncSession, bot: Bot, bill_id: int, target_user_id: int, acting_user_id: int
) -> tuple[bool, str]:
    if target_user_id != acting_user_id:
        return False, strings.NOT_YOUR_SHARE

    share = (
        await session.execute(
            select(BillShare).where(BillShare.bill_id == bill_id, BillShare.user_id == acting_user_id)
        )
    ).scalar_one_or_none()
    if share is None:
        return False, strings.NOT_YOUR_SHARE

    share.paid = not share.paid
    share.paid_at = dt.datetime.utcnow() if share.paid else None
    await session.flush()

    bill, shares = await get_bill_with_shares(session, bill_id)
    users_by_id = await _users_by_id(session, [s.user_id for s in shares])
    text, keyboard = render_bill(bill, shares, users_by_id)
    await bot.edit_message_text(
        chat_id=settings.house_channel_id,
        message_id=bill.channel_message_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    return True, ""


async def get_unpaid_shares_for_user(session: AsyncSession, user_id: int) -> list[tuple[BillShare, Bill]]:
    result = await session.execute(
        select(BillShare, Bill)
        .join(Bill, BillShare.bill_id == Bill.id)
        .where(BillShare.user_id == user_id, BillShare.paid == False)  # noqa: E712
        .order_by(Bill.created_at.desc())
    )
    return list(result.all())


async def get_bills_history_page(session: AsyncSession, page: int, page_size: int = 5) -> tuple[list[Bill], bool]:
    result = await session.execute(
        select(Bill).order_by(Bill.created_at.desc()).offset(page * page_size).limit(page_size + 1)
    )
    rows = list(result.scalars().all())
    has_next = len(rows) > page_size
    return rows[:page_size], has_next


async def is_bill_settled(session: AsyncSession, bill_id: int) -> bool:
    count = (
        await session.execute(
            select(func.count()).select_from(BillShare).where(BillShare.bill_id == bill_id, BillShare.paid == False)  # noqa: E712
        )
    ).scalar()
    return count == 0


async def get_balances(session: AsyncSession) -> dict[int, int]:
    """Total unpaid cents owed per user, across all open bills."""
    result = await session.execute(
        select(BillShare.user_id, func.sum(BillShare.amount_cents))
        .where(BillShare.paid == False)  # noqa: E712
        .group_by(BillShare.user_id)
    )
    return {uid: total for uid, total in result.all()}
