import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.db.models import Base, User


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as s:
        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def make_user(session: AsyncSession):
    async def _make_user(telegram_id: int) -> User:
        user = User(telegram_id=telegram_id, display_name=f"User {telegram_id}", is_registered=True)
        session.add(user)
        await session.flush()
        return user

    return _make_user


class FakeMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id


class FakeBot:
    """Stands in for aiogram's Bot in service-level tests — records calls
    instead of hitting the Telegram API."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edited: list[dict] = []
        self._next_message_id = 1

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        message = FakeMessage(message_id=self._next_message_id)
        self._next_message_id += 1
        self.sent.append(
            {"chat_id": chat_id, "text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
        )
        return message

    async def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode=None):
        self.edited.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )


@pytest.fixture
def fake_bot() -> FakeBot:
    return FakeBot()
