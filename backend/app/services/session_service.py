from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

logger = logging.getLogger(__name__)

# UUID v4 pattern — used to reject obviously invalid or malicious session IDs.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# At most this many history rows are kept per session.
_HISTORY_CAP = 50

# Identical query within this window is not re-logged (dedup).
_DEDUP_WINDOW = timedelta(seconds=300)


def is_valid_session_id(session_id: str) -> bool:
    return bool(_UUID_RE.match(session_id))


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

async def upsert_session(pool, session_id: str, platform: str | None = None) -> None:
    """Create session row on first visit; bump last_seen_at on subsequent visits."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (id, platform)
            VALUES ($1, $2)
            ON CONFLICT (id) DO UPDATE SET last_seen_at = NOW()
            """,
            session_id,
            platform,
        )


async def delete_session(pool, session_id: str) -> None:
    """Hard-delete session and all its history / favourites (cascade)."""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)


# ---------------------------------------------------------------------------
# Search history
# ---------------------------------------------------------------------------

async def log_search(
    pool,
    session_id: str,
    query_text: str,
    parsed_query: dict[str, Any] | None,
    result_count: int,
    fallback_mode: str | None,
) -> None:
    """Append a search record; dedup identical queries within _DEDUP_WINDOW."""
    async with pool.acquire() as conn:
        # Skip if the same text was logged recently
        recent = await conn.fetchval(
            """
            SELECT id FROM search_history
            WHERE session_id = $1
              AND query_text  = $2
              AND created_at  > NOW() - $3::INTERVAL
            LIMIT 1
            """,
            session_id,
            query_text,
            _DEDUP_WINDOW,
        )
        if recent:
            return

        await conn.execute(
            """
            INSERT INTO search_history
                (session_id, query_text, parsed_query, result_count, fallback_mode)
            VALUES ($1, $2, $3, $4, $5)
            """,
            session_id,
            query_text,
            parsed_query,   # dict → JSONB via codec registered in db.py
            result_count,
            fallback_mode,
        )

        # Trim to _HISTORY_CAP rows, keeping the newest
        await conn.execute(
            """
            DELETE FROM search_history
            WHERE id IN (
                SELECT id FROM search_history
                WHERE session_id = $1
                ORDER BY created_at DESC
                OFFSET $2
            )
            """,
            session_id,
            _HISTORY_CAP,
        )


async def get_history(
    pool, session_id: str, limit: int = 20
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT query_text, parsed_query, result_count, fallback_mode, created_at
            FROM search_history
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            session_id,
            limit,
        )
    return [
        {
            "query_text":    r["query_text"],
            "parsed_query":  r["parsed_query"],   # already a dict (codec decoded)
            "result_count":  r["result_count"],
            "fallback_mode": r["fallback_mode"],
            "created_at":    r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def clear_history(pool, session_id: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM search_history WHERE session_id = $1",
            session_id,
        )


# ---------------------------------------------------------------------------
# Favourites
# ---------------------------------------------------------------------------

async def get_favourites(pool, session_id: str) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT artwork_id, source_api, candidate, created_at
            FROM favourites
            WHERE session_id = $1
            ORDER BY created_at DESC
            """,
            session_id,
        )
    return [
        {
            "artwork_id": r["artwork_id"],
            "source_api": r["source_api"],
            "candidate":  r["candidate"],   # dict (codec decoded)
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def add_favourite(pool, session_id: str, candidate: dict[str, Any]) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO favourites (session_id, artwork_id, source_api, candidate)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (session_id, artwork_id, source_api) DO NOTHING
            """,
            session_id,
            candidate["id"],
            candidate["source_api"],
            candidate,   # dict → JSONB via codec
        )


async def remove_favourite(
    pool, session_id: str, artwork_id: str, source_api: str
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            DELETE FROM favourites
            WHERE session_id = $1
              AND artwork_id  = $2
              AND source_api  = $3
            """,
            session_id,
            artwork_id,
            source_api,
        )
