"""Button-driven admin panels.

Everything here is reachable from the ⚙️ menu without typing a command:
managing who counts as a housemate, and reordering the trash / cleaning
rotations. The slash commands in handlers/admin.py still work and remain
the way to change reminder times.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import strings
from bot.config import settings
from bot.db.models import CleaningRotation, TrashRotation, User
from bot.services import admin as admin_service
from bot.services import rotation, settings_store

router = Router(name="admin_ui")

TRASH = "trash"
CLEANING = "clean"

# Per-rotation wiring: model, the Settings key holding "whose turn it is",
# and the panel heading.
_ROTATIONS = {
    TRASH: (TrashRotation, settings_store.TRASH_CURRENT_POSITION, strings.ROTATION_TRASH_HEADER),
    CLEANING: (CleaningRotation, settings_store.CLEANING_CURRENT_POSITION, strings.ROTATION_CLEANING_HEADER),
}

_BUTTON_NAME_LIMIT = 20


class HouseCB(CallbackData, prefix="house"):
    action: str  # "toggle" | "open"
    user_id: int


class RotCB(CallbackData, prefix="rot"):
    kind: str  # "trash" | "clean"
    action: str  # "open" | "up" | "down" | "remove" | "add" | "noop"
    user_id: int


class HousemateAdd(StatesGroup):
    telegram_id = State()
    display_name = State()


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_id_set


def _short(name: str) -> str:
    return name if len(name) <= _BUTTON_NAME_LIMIT else name[: _BUTTON_NAME_LIMIT - 1] + "…"


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=strings.ADMIN_PANEL_HOUSEMATES_BUTTON, callback_data="admin_panel:housemates")],
            [
                InlineKeyboardButton(
                    text=strings.ADMIN_PANEL_TRASH_ROTATION_BUTTON,
                    callback_data=RotCB(kind=TRASH, action="open", user_id=0).pack(),
                ),
                InlineKeyboardButton(
                    text=strings.ADMIN_PANEL_CLEANING_ROTATION_BUTTON,
                    callback_data=RotCB(kind=CLEANING, action="open", user_id=0).pack(),
                ),
            ],
            [InlineKeyboardButton(text=strings.ADMIN_ANNOUNCE_BUTTON, callback_data="admin_menu:announce")],
        ]
    )


async def _edit_in_place(query: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    """Refreshes the panel the admin is looking at. Telegram rejects an edit
    that changes nothing, which is harmless here."""
    try:
        await query.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        pass


# --------------------------------------------------------------------------
# Housemates panel
# --------------------------------------------------------------------------
async def render_housemates(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    users = await admin_service.list_housemates(session)

    if not users:
        text = f"{strings.HOUSEMATES_HEADER}\n\n{strings.HOUSEMATES_EMPTY}"
    else:
        text = f"{strings.HOUSEMATES_HEADER}\n\n{strings.HOUSEMATES_HINT}"

    rows = [
        [
            InlineKeyboardButton(
                text=(strings.HOUSEMATE_ROW_ACTIVE if user.is_active else strings.HOUSEMATE_ROW_INACTIVE).format(
                    name=_short(user.display_name)
                ),
                callback_data=HouseCB(action="toggle", user_id=user.telegram_id).pack(),
            )
        ]
        for user in users
    ]
    rows.append(
        [InlineKeyboardButton(text=strings.HOUSEMATE_ADD_MANUAL_BUTTON, callback_data="admin_panel:add_housemate")]
    )
    rows.append([InlineKeyboardButton(text=strings.ADMIN_PANEL_BACK_BUTTON, callback_data="admin_panel:root")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin_panel:root")
async def open_root_panel(query: CallbackQuery) -> None:
    if not _is_admin(query.from_user.id):
        await query.answer(strings.NOT_ADMIN, show_alert=True)
        return
    await query.answer()
    await _edit_in_place(query, strings.ADMIN_MENU_TEXT, admin_panel_keyboard())


@router.message(Command("housemates"))
async def cmd_housemates(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(strings.NOT_ADMIN)
        return
    text, keyboard = await render_housemates(session)
    await message.answer(text, reply_markup=keyboard)


@router.callback_query(F.data == "admin_panel:housemates")
async def open_housemates(query: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(query.from_user.id):
        await query.answer(strings.NOT_ADMIN, show_alert=True)
        return
    await query.answer()
    text, keyboard = await render_housemates(session)
    await _edit_in_place(query, text, keyboard)


@router.callback_query(HouseCB.filter(F.action == "toggle"))
async def toggle_housemate(query: CallbackQuery, callback_data: HouseCB, session: AsyncSession) -> None:
    if not _is_admin(query.from_user.id):
        await query.answer(strings.NOT_ADMIN, show_alert=True)
        return

    user = await session.get(User, callback_data.user_id)
    if user is None:
        await query.answer(strings.ADMIN_HOUSEMATE_NOT_FOUND, show_alert=True)
        return

    if user.is_active:
        await admin_service.remove_housemate(session, user.telegram_id)
        toast = strings.HOUSEMATE_TOGGLED_OFF.format(name=user.display_name)
        action = "panel_deactivate_housemate"
    else:
        await admin_service.reactivate_housemate(session, user.telegram_id)
        toast = strings.HOUSEMATE_TOGGLED_ON.format(name=user.display_name)
        action = "panel_reactivate_housemate"

    await admin_service.log_action(session, query.from_user.id, action, str(user.telegram_id))
    await query.answer(toast)
    text, keyboard = await render_housemates(session)
    await _edit_in_place(query, text, keyboard)


@router.callback_query(StateFilter(None), F.data == "admin_panel:add_housemate")
async def start_add_housemate(query: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(query.from_user.id):
        await query.answer(strings.NOT_ADMIN, show_alert=True)
        return
    await state.set_state(HousemateAdd.telegram_id)
    await query.answer()
    await query.message.answer(strings.HOUSEMATE_ADD_ASK_ID)


@router.message(HousemateAdd.telegram_id)
async def process_housemate_id(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer(strings.HOUSEMATE_ADD_INVALID_ID)
        return
    await state.update_data(telegram_id=int(raw))
    await state.set_state(HousemateAdd.display_name)
    await message.answer(strings.HOUSEMATE_ADD_ASK_NAME)


@router.message(HousemateAdd.display_name)
async def process_housemate_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer(strings.HOUSEMATE_ADD_ASK_NAME)
        return

    data = await state.get_data()
    user = await admin_service.add_housemate(session, data["telegram_id"], name)
    await admin_service.log_action(session, message.from_user.id, "panel_add_housemate", str(user.telegram_id))
    await state.clear()

    await message.answer(strings.ADMIN_HOUSEMATE_ADDED.format(name=user.display_name))
    text, keyboard = await render_housemates(session)
    await message.answer(text, reply_markup=keyboard)


# --------------------------------------------------------------------------
# Rotation panels
# --------------------------------------------------------------------------
async def render_rotation(session: AsyncSession, kind: str) -> tuple[str, InlineKeyboardMarkup]:
    model, position_key, header = _ROTATIONS[kind]
    queue = await rotation.get_ordered_queue(session, model)
    current = await settings_store.get_int(session, position_key, 0)

    lines = [header, ""]
    rows: list[list[InlineKeyboardButton]] = []

    if not queue:
        lines.append(strings.ROTATION_PANEL_EMPTY)
    else:
        lines.append(strings.ROTATION_PANEL_HINT)
        lines.append("")
        for index, entry in enumerate(queue):
            user = await session.get(User, entry.user_id)
            name = user.display_name if user else str(entry.user_id)
            marker = strings.ROTATION_CURRENT_MARKER if index == current % len(queue) else ""
            lines.append(strings.ROTATION_PANEL_LINE.format(marker=marker, position=index + 1, name=name))
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⬆️", callback_data=RotCB(kind=kind, action="up", user_id=entry.user_id).pack()
                    ),
                    InlineKeyboardButton(
                        text=f"{index + 1}. {_short(name)}",
                        callback_data=RotCB(kind=kind, action="noop", user_id=entry.user_id).pack(),
                    ),
                    InlineKeyboardButton(
                        text="⬇️", callback_data=RotCB(kind=kind, action="down", user_id=entry.user_id).pack()
                    ),
                    InlineKeyboardButton(
                        text="❌", callback_data=RotCB(kind=kind, action="remove", user_id=entry.user_id).pack()
                    ),
                ]
            )

    # Active housemates who aren't in this rotation can be added back.
    in_queue = {entry.user_id for entry in queue}
    for user in await admin_service.list_housemates(session):
        if user.is_active and user.telegram_id not in in_queue:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=strings.ROTATION_ADD_MISSING_LABEL.format(name=_short(user.display_name)),
                        callback_data=RotCB(kind=kind, action="add", user_id=user.telegram_id).pack(),
                    )
                ]
            )

    rows.append([InlineKeyboardButton(text=strings.ADMIN_PANEL_BACK_BUTTON, callback_data="admin_panel:root")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("rotations"))
async def cmd_rotations(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await message.answer(strings.NOT_ADMIN)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=strings.ADMIN_PANEL_TRASH_ROTATION_BUTTON,
                    callback_data=RotCB(kind=TRASH, action="open", user_id=0).pack(),
                ),
                InlineKeyboardButton(
                    text=strings.ADMIN_PANEL_CLEANING_ROTATION_BUTTON,
                    callback_data=RotCB(kind=CLEANING, action="open", user_id=0).pack(),
                ),
            ]
        ]
    )
    await message.answer(strings.ROTATION_PICK_HEADER, reply_markup=keyboard)


@router.callback_query(RotCB.filter())
async def handle_rotation_action(query: CallbackQuery, callback_data: RotCB, session: AsyncSession) -> None:
    if not _is_admin(query.from_user.id):
        await query.answer(strings.NOT_ADMIN, show_alert=True)
        return

    kind = callback_data.kind
    if kind not in _ROTATIONS:
        await query.answer(strings.NOTHING_TO_SHOW, show_alert=True)
        return
    model, position_key, _ = _ROTATIONS[kind]
    action = callback_data.action

    if action == "open":
        await query.answer()
        text, keyboard = await render_rotation(session, kind)
        await _edit_in_place(query, text, keyboard)
        return

    if action == "noop":
        # The middle label button — it exists to name the row, not to act.
        await query.answer()
        return

    user = await session.get(User, callback_data.user_id)
    name = user.display_name if user else str(callback_data.user_id)

    if action in ("up", "down"):
        moved = await rotation.move_user(
            session, model, position_key, callback_data.user_id, -1 if action == "up" else 1
        )
        await query.answer(strings.ROTATION_MOVED if moved else strings.ROTATION_AT_EDGE)
        if not moved:
            return
        await admin_service.log_action(
            session, query.from_user.id, f"rotation_{kind}_{action}", str(callback_data.user_id)
        )
    elif action == "remove":
        await rotation.remove_user_keeping_turn(session, model, position_key, callback_data.user_id)
        await admin_service.log_action(
            session, query.from_user.id, f"rotation_{kind}_remove", str(callback_data.user_id)
        )
        await query.answer(strings.ROTATION_USER_REMOVED.format(name=name))
    elif action == "add":
        await rotation.add_user_keeping_turn(session, model, position_key, callback_data.user_id)
        await admin_service.log_action(
            session, query.from_user.id, f"rotation_{kind}_add", str(callback_data.user_id)
        )
        await query.answer(strings.ROTATION_USER_ADDED.format(name=name))
    else:
        await query.answer()
        return

    text, keyboard = await render_rotation(session, kind)
    await _edit_in_place(query, text, keyboard)
