from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    last_membership_check_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class TrashRotation(Base):
    """Single shared round-robin queue over all housemates for trash duty."""

    __tablename__ = "trash_rotation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position: Mapped[int] = mapped_column(Integer, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))

    user: Mapped[User] = relationship()


class TrashLog(Base):
    __tablename__ = "trash_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[dt.date] = mapped_column(Date)
    trash_type: Mapped[str] = mapped_column(String(64))
    assigned_user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending / done / skipped_not_full
    responded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    assigned_user: Mapped[User] = relationship()


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Money stored as integer cents — SQLite has no native fixed-point
    # decimal type, so Numeric columns round-trip through floats and risk
    # rounding drift; cents avoids that entirely.
    total_amount_cents: Mapped[int] = mapped_column(Integer)
    per_person_amount_cents: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    creator: Mapped[User] = relationship()
    shares: Mapped[list["BillShare"]] = relationship(back_populates="bill", cascade="all, delete-orphan")


class BillShare(Base):
    __tablename__ = "bill_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bill_id: Mapped[int] = mapped_column(Integer, ForeignKey("bills.id"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    # Per-share amount in cents, so the rounding remainder (v1 rule: goes to
    # the bill creator, see services/bills.py) can differ from
    # bill.per_person_amount_cents.
    amount_cents: Mapped[int] = mapped_column(Integer)
    paid: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)

    bill: Mapped[Bill] = relationship(back_populates="shares")
    user: Mapped[User] = relationship()


class ShoppingItem(Base):
    __tablename__ = "shopping_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    added_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    added_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    purchased_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.telegram_id"), nullable=True)
    purchased_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ShoppingListMessage(Base):
    """Singleton row tracking the pinned shopping-list message in the channel."""

    __tablename__ = "shopping_list_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class CleaningRotation(Base):
    """Single shared round-robin queue over all housemates for cleaning turns."""

    __tablename__ = "cleaning_rotation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position: Mapped[int] = mapped_column(Integer, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))

    user: Mapped[User] = relationship()


class CleaningLog(Base):
    __tablename__ = "cleaning_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    week_start_date: Mapped[dt.date] = mapped_column(Date)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    section: Mapped[str] = mapped_column(String(32))  # kitchen / hall / bathroom
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending / done / skipped_not_needed
    responded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)

    user: Mapped[User] = relationship()


class Settings(Base):
    """Admin-configurable key/value settings (reminder times, rotation anchors, etc.)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    action: Mapped[str] = mapped_column(String(128))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
