import os
import re

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings


def _get_schema_and_clean_url(url: str) -> tuple[str, str]:
    """Extract schema from URL options and return (schema, clean_url).

    asyncpg doesn't support the 'options' URL parameter that sets search_path.
    We need to extract it and use server_settings instead.
    """
    # Match options=-csearch_path%3D{schema} or options=-c+search_path={schema}
    # URL-encoded: %3D is =, %26 is &
    match = re.search(r"[?&]options=-c(?:\+|%20)?search_path(?:%3D|=)(\w+)", url, re.IGNORECASE)
    if match:
        schema = match.group(1)
        # Remove the options parameter from URL
        clean_url = re.sub(r"[?&]options=-c(?:\+|%20)?search_path(?:%3D|=)\w+", "", url)
        # Fix URL if we removed the first query param (? becomes nothing)
        clean_url = re.sub(r"\?&", "?", clean_url)
        clean_url = re.sub(r"\?$", "", clean_url)
        return schema, clean_url

    # Fall back to ENVIRONMENT variable
    env = os.getenv("ENVIRONMENT", "").lower()
    if env in ("dev", "staging", "prod"):
        return env, url

    return "public", url


# Parse schema from DATABASE_URL and get clean URL for asyncpg
_db_schema, _clean_db_url = _get_schema_and_clean_url(settings.DATABASE_URL)

# Supabase pooler (pgbouncer transaction mode) configuration
# - NullPool: Let Supabase handle connection pooling, not SQLAlchemy
# - statement_cache_size=0: Disable asyncpg's prepared statement cache
# - prepared_statement_name_func: Use unnamed statements to avoid conflicts
# - server_settings: Set search_path for schema isolation + public for pgvector
_search_path = f"{_db_schema},public"
engine = create_async_engine(
    _clean_db_url,
    echo=settings.DEBUG,
    poolclass=NullPool,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: "",
        "server_settings": {"search_path": _search_path},
    },
)

# Single session factory using modern async_sessionmaker (SQLAlchemy 2.0+)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    """Dependency that yields a database session for request scope."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_session_factory():
    """Return the session factory for use in streaming endpoints and tests."""
    return async_session_factory
