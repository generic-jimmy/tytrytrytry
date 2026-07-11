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


# -------------------------------------------------------------- migrations --
# The app originally shipped without Alembic. create_all() handles missing
# tables but won't ALTER existing ones — which means upgrading an existing
# deployment (with the old schema) crashes the moment any code path touches
# a new column on an existing table.
#
# This map lists every column we've added to existing tables since the
# original release. _run_lightweight_migrations() runs ADD COLUMN IF NOT
# EXISTS for each one on every boot — idempotent, safe, no data loss.

# Format: table_name -> [(column_name, SQL type spec, default SQL or None)]
_COLUMN_ADDITIONS = {
    "admins": [
        ("role", "VARCHAR(20)", "'admin'"),
        ("display_name", "VARCHAR(255)", "''"),
    ],
    "groups": [
        ("dashboard_theme", "VARCHAR(20)", "'dark'"),
    ],
    "mod_log": [
        ("admin_id", "BIGINT", "NULL"),
    ],
}


async def _run_lightweight_migrations() -> None:
    """Adds new columns to existing tables that were added after the original
    release. Idempotent — only runs ADD COLUMN when the column is actually
    missing. Safe on every boot, fresh or upgraded."""
    from sqlalchemy import inspect as sa_inspect, text

    def _inspect_sync(conn):
        """Sync helper that runs inside run_sync — returns a dict of
        {table_name: set(column_names)} for every table currently in the DB."""
        insp = sa_inspect(conn)
        return {
            t: {c["name"] for c in insp.get_columns(t)}
            for t in insp.get_table_names()
        }

    async with engine.begin() as conn:
        # Inspection must run inside run_sync — async connections don't
        # support inspect() directly.
        existing = await conn.run_sync(_inspect_sync)

        for table_name, columns in _COLUMN_ADDITIONS.items():
            # If the whole table is missing, create_all() above already made
            # it with the full schema — no ALTER needed.
            if table_name not in existing:
                continue

            existing_cols = existing[table_name]
            for col_name, col_type, default in columns:
                if col_name in existing_cols:
                    continue

                # Build ALTER TABLE statement. The default is required for
                # NOT NULL columns added to a populated table; we make every
                # new column nullable or give it a default to be safe.
                sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_type}'
                if default is not None:
                    sql += f" DEFAULT {default}"
                await conn.execute(text(sql))


async def init_models() -> None:
    """Creates tables if they don't already exist, then runs idempotent
    ALTER TABLE migrations to add new columns to pre-existing tables.

    Once this is running for real and holding data you care about, switch to
    Alembic migrations instead of relying on this to catch up on schema
    changes — it won't handle column type changes or drops, only additions."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _run_lightweight_migrations()
