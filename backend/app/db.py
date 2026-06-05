from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema — applied idempotently on every startup
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id            UUID        PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    platform      TEXT,
    metadata      JSONB       NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS search_history (
    id            BIGSERIAL   PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    query_text    TEXT        NOT NULL,
    parsed_query  JSONB,
    result_count  INT,
    fallback_mode TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_history_session
    ON search_history (session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS favourites (
    id            BIGSERIAL   PRIMARY KEY,
    session_id    UUID        NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    artwork_id    TEXT        NOT NULL,
    source_api    TEXT        NOT NULL,
    candidate     JSONB       NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (session_id, artwork_id, source_api)
);

CREATE INDEX IF NOT EXISTS idx_favourites_session
    ON favourites (session_id, created_at DESC);
"""


# ---------------------------------------------------------------------------
# Connection codec — teach asyncpg to auto-serialize Python dicts ↔ JSONB
# ---------------------------------------------------------------------------

async def _init_conn(conn) -> None:
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
        format="text",
    )


# ---------------------------------------------------------------------------
# Pool factory
# ---------------------------------------------------------------------------

async def create_pool():
    """Create asyncpg pool, apply schema, and return pool.

    Raises RuntimeError if asyncpg is not installed or DATABASE_URL is unset.
    """
    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError(
            "asyncpg is not installed. Run: pip install asyncpg"
        ) from exc

    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    pool = await asyncpg.create_pool(
        url,
        min_size=2,
        max_size=10,
        init=_init_conn,
    )

    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_SQL)

    logger.info("PostgreSQL pool ready — schema applied")
    return pool
