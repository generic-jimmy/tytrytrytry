from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def _to_asyncpg_url(url: str) -> str:
    """Supabase gives you a postgresql:// URL — SQLAlchemy's async engine
    needs the +asyncpg driver suffix. Handles both postgres:// and
    postgresql:// prefixes."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_to_asyncpg_url(settings.database_url), pool_pre_ping=True)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_models() -> None:
    """MVP-only convenience: creates tables if they don't already exist.
    Once this is running for real and holding data you care about, switch to
    Alembic migrations instead of relying on this to catch up on schema
    changes — it won't alter existing tables, only create missing ones."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
