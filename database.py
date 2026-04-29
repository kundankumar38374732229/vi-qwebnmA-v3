import asyncpg
import asyncio
from datetime import datetime, date, timezone
from typing import Optional
import uuid

from config import DATABASE_URL

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def init_db():
    """Create all tables if they don't exist. Run once on startup."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id        BIGINT PRIMARY KEY,
                username       TEXT,
                joined_at      TIMESTAMPTZ DEFAULT NOW(),
                watch_count    INT DEFAULT 0,
                last_reset     DATE DEFAULT CURRENT_DATE,
                unlocked_until TIMESTAMPTZ,
                referred_by    BIGINT,
                referral_count INT DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS admins (
                user_id   BIGINT PRIMARY KEY,
                added_by  BIGINT,
                added_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS videos (
                uuid               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                file_id            TEXT NOT NULL,
                title              TEXT,
                uploaded_by        BIGINT,
                uploaded_at        TIMESTAMPTZ DEFAULT NOW(),
                delete_after_mins  INT DEFAULT 30
            );

            CREATE TABLE IF NOT EXISTS deliveries (
                id                  SERIAL PRIMARY KEY,
                user_id             BIGINT NOT NULL,
                video_uuid          UUID NOT NULL,
                delivered_at        TIMESTAMPTZ DEFAULT NOW(),
                message_id          BIGINT,
                chat_id             BIGINT,
                delete_at           TIMESTAMPTZ,
                deleted             BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS unlock_tokens (
                token       TEXT PRIMARY KEY,
                user_id     BIGINT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                expires_at  TIMESTAMPTZ NOT NULL,
                used        BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS required_groups (
                chat_id     BIGINT PRIMARY KEY,
                title       TEXT NOT NULL,
                invite_link TEXT NOT NULL,
                added_at    TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id            SERIAL PRIMARY KEY,
                referrer_id   BIGINT NOT NULL,
                referee_id    BIGINT NOT NULL UNIQUE,
                completed     BOOLEAN DEFAULT FALSE,
                completed_at  TIMESTAMPTZ
            );
        """)

        # Migration: add new columns to existing users table if not present
        await conn.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS referred_by BIGINT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_count INT DEFAULT 0;
        """)

    print("✅ Database initialized.")


# ── USER ──────────────────────────────────────────────────────────────────────

async def get_or_create_user(user_id: int, username: str = None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id = $1", user_id
        )
        if not row:
            row = await conn.fetchrow(
                """INSERT INTO users (user_id, username)
                   VALUES ($1, $2)
                   RETURNING *""",
                user_id, username
            )
        return dict(row)


async def get_user(user_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id = $1", user_id
        )
        return dict(row) if row else None


async def reset_daily_count_if_needed(user_id: int):
    """Reset watch_count if it's a new day for this user."""
    pool = await get_pool()
    today = date.today()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE users
               SET watch_count = 0, last_reset = $1
               WHERE user_id = $2 AND last_reset < $1""",
            today, user_id
        )


async def increment_watch_count(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET watch_count = watch_count + 1 WHERE user_id = $1",
            user_id
        )


async def set_unlocked_until(user_id: int, until: datetime):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET unlocked_until = $1 WHERE user_id = $2",
            until, user_id
        )


def is_user_unlocked(user: dict) -> bool:
    if not user.get("unlocked_until"):
        return False
    return user["unlocked_until"] > datetime.now(timezone.utc)


# ── ADMIN ─────────────────────────────────────────────────────────────────────

async def is_admin(user_id: int) -> bool:
    from config import SUPER_ADMIN_IDS
    if user_id in SUPER_ADMIN_IDS:
        return True
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM admins WHERE user_id = $1", user_id
        )
        return row is not None


async def add_admin(user_id: int, added_by: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO admins (user_id, added_by)
               VALUES ($1, $2)
               ON CONFLICT (user_id) DO NOTHING""",
            user_id, added_by
        )


async def remove_admin(user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM admins WHERE user_id = $1", user_id)


# ── VIDEOS ────────────────────────────────────────────────────────────────────

async def save_video(file_id: str, title: str, uploaded_by: int, delete_after_mins: int) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO videos (file_id, title, uploaded_by, delete_after_mins)
               VALUES ($1, $2, $3, $4)
               RETURNING uuid""",
            file_id, title, uploaded_by, delete_after_mins
        )
        return str(row["uuid"])


async def get_video(video_uuid: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM videos WHERE uuid = $1", uuid.UUID(video_uuid)
        )
        return dict(row) if row else None


async def list_videos() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM videos ORDER BY uploaded_at DESC"
        )
        return [dict(r) for r in rows]


async def delete_video(video_uuid: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM videos WHERE uuid = $1", uuid.UUID(video_uuid)
        )


# ── DELIVERIES ────────────────────────────────────────────────────────────────

async def save_delivery(user_id: int, video_uuid: str, message_id: int,
                        chat_id: int, delete_at: datetime) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO deliveries
               (user_id, video_uuid, message_id, chat_id, delete_at)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id""",
            user_id, uuid.UUID(video_uuid), message_id, chat_id, delete_at
        )
        return row["id"]


async def mark_delivery_deleted(delivery_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE deliveries SET deleted = TRUE WHERE id = $1", delivery_id
        )


async def get_pending_deletions() -> list:
    """Fetch all undeleted deliveries whose delete_at has passed. Used on restart."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM deliveries
               WHERE deleted = FALSE AND delete_at <= NOW()"""
        )
        return [dict(r) for r in rows]


async def get_future_deletions() -> list:
    """Fetch all undeleted deliveries scheduled for the future. Used on restart."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM deliveries
               WHERE deleted = FALSE AND delete_at > NOW()"""
        )
        return [dict(r) for r in rows]


# ── UNLOCK TOKENS ─────────────────────────────────────────────────────────────

async def create_unlock_token(user_id: int, expiry_minutes: int) -> str:
    token = str(uuid.uuid4()).replace("-", "")[:20]
    expires_at = datetime.now(timezone.utc)
    from datetime import timedelta
    expires_at = expires_at + timedelta(minutes=expiry_minutes)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO unlock_tokens (token, user_id, expires_at)
               VALUES ($1, $2, $3)""",
            token, user_id, expires_at
        )
    return token


async def consume_unlock_token(token: str) -> Optional[int]:
    """Validate and consume token by token string. Returns user_id if valid, else None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM unlock_tokens
               WHERE token = $1 AND used = FALSE AND expires_at > NOW()""",
            token
        )
        if not row:
            return None
        await conn.execute(
            "UPDATE unlock_tokens SET used = TRUE WHERE token = $1", token
        )
        return row["user_id"]


async def consume_pending_unlock_token(user_id: int) -> bool:
    """
    Called when user lands on bot after watching VPLink ad.
    Finds this user's most recent valid (unused, non-expired) token and consumes it.
    Returns True if a valid token was found and consumed, False otherwise.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT token FROM unlock_tokens
               WHERE user_id = $1 AND used = FALSE AND expires_at > NOW()
               ORDER BY created_at DESC
               LIMIT 1""",
            user_id
        )
        if not row:
            return False
        await conn.execute(
            "UPDATE unlock_tokens SET used = TRUE WHERE token = $1", row["token"]
        )
        return True


# ── STATS ─────────────────────────────────────────────────────────────────────

async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_videos = await conn.fetchval("SELECT COUNT(*) FROM videos")
        total_deliveries = await conn.fetchval("SELECT COUNT(*) FROM deliveries")
        unlocked_now = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE unlocked_until > NOW()"
        )
        return {
            "total_users": total_users,
            "total_videos": total_videos,
            "total_deliveries": total_deliveries,
            "unlocked_now": unlocked_now,
        }


# ── REQUIRED GROUPS (DB-managed) ──────────────────────────────────────────────

async def get_required_groups() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM required_groups ORDER BY added_at ASC"
        )
        return [dict(r) for r in rows]


async def add_required_group(chat_id: int, title: str, invite_link: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO required_groups (chat_id, title, invite_link)
               VALUES ($1, $2, $3)
               ON CONFLICT (chat_id) DO UPDATE
               SET title = $2, invite_link = $3""",
            chat_id, title, invite_link
        )


async def remove_required_group(chat_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM required_groups WHERE chat_id = $1", chat_id
        )


# ── REFERRALS ─────────────────────────────────────────────────────────────────

async def set_referred_by(referee_id: int, referrer_id: int):
    """Record who referred this user. Only set once."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Update user's referred_by if not already set
        await conn.execute(
            """UPDATE users SET referred_by = $1
               WHERE user_id = $2 AND referred_by IS NULL""",
            referrer_id, referee_id
        )
        # Insert referral record
        await conn.execute(
            """INSERT INTO referrals (referrer_id, referee_id)
               VALUES ($1, $2)
               ON CONFLICT (referee_id) DO NOTHING""",
            referrer_id, referee_id
        )


async def complete_referral(referee_id: int) -> Optional[int]:
    """
    Mark a referral as completed (called when referee joins all groups).
    Returns referrer_id if this was a new completion, else None.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT referrer_id FROM referrals
               WHERE referee_id = $1 AND completed = FALSE""",
            referee_id
        )
        if not row:
            return None
        referrer_id = row["referrer_id"]
        await conn.execute(
            """UPDATE referrals SET completed = TRUE, completed_at = NOW()
               WHERE referee_id = $1""",
            referee_id
        )
        await conn.execute(
            """UPDATE users SET referral_count = referral_count + 1
               WHERE user_id = $1""",
            referrer_id
        )
        return referrer_id


async def get_referral_stats(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = $1", user_id
        )
        completed = await conn.fetchval(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = $1 AND completed = TRUE",
            user_id
        )
        user = await conn.fetchrow(
            "SELECT referral_count FROM users WHERE user_id = $1", user_id
        )
        return {
            "total_referred": total,
            "completed": completed,
            "referral_count": user["referral_count"] if user else 0,
        }
