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
