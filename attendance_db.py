import os
from datetime import date

import asyncpg

_pool: asyncpg.Pool | None = None
_db_disabled = False


async def init_db() -> None:
    """Initialize the asyncpg pool and ensure the attendance_log table exists."""
    global _pool, _db_disabled

    if _pool or _db_disabled:
        return

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("⚠️ DATABASE_URL not set; attendance DB logging disabled.")
        _db_disabled = True
        return

    try:
        _pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=4)
        async with _pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS attendance_log (
                    date date NOT NULL,
                    channel_id bigint NOT NULL,
                    channel_name text NOT NULL,
                    member_id bigint NOT NULL,
                    member_name text NOT NULL,
                    status text NOT NULL,
                    PRIMARY KEY (date, channel_id, member_id)
                )
                """
            )
        print("✅ Attendance DB initialized.")
    except Exception as exc:
        print(f"⚠️ Failed to initialize attendance DB: {exc}")
        _db_disabled = True


async def log_day(date_obj: date, channel, present_ids: set[int], all_humans: list) -> None:
    """Log a snapshot of attendance for every human member in the channel."""
    if _db_disabled or _pool is None:
        return

    async with _pool.acquire() as conn:
        async with conn.transaction():
            for member in all_humans:
                status = "present" if member.id in present_ids else "absent"
                await conn.execute(
                    """
                    INSERT INTO attendance_log (
                        date,
                        channel_id,
                        channel_name,
                        member_id,
                        member_name,
                        status
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (date, channel_id, member_id)
                    DO UPDATE SET
                        channel_name = EXCLUDED.channel_name,
                        member_name  = EXCLUDED.member_name,
                        status       = EXCLUDED.status
                    """,
                    date_obj,
                    channel.id,
                    channel.name,
                    member.id,
                    member.display_name,
                    status,
                )


async def get_month_records(channel_id: int, year: int, month: int) -> dict[int, dict[str, int]]:
    """Return aggregate attendance for a channel during a month."""
    if _db_disabled or _pool is None:
        return {}

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                member_id,
                member_name,
                SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) AS present,
                COUNT(*) AS total
            FROM attendance_log
            WHERE channel_id = $1
              AND date >= make_date($2, $3, 1)
              AND date < (make_date($2, $3, 1) + INTERVAL '1 month')::date
            GROUP BY member_id, member_name
            ORDER BY member_name
            """,
            channel_id,
            year,
            month,
        )

    return {
        row["member_id"]: {
            "name": row["member_name"],
            "present": row["present"],
            "total": row["total"],
        }
        for row in rows
    }


async def get_logged_dates(channel_id: int, year: int, month: int) -> list[str]:
    """Return the distinct dates that were logged for a channel during a month."""
    if _db_disabled or _pool is None:
        return []

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT date
            FROM attendance_log
            WHERE channel_id = $1
              AND date >= make_date($2, $3, 1)
              AND date < (make_date($2, $3, 1) + INTERVAL '1 month')::date
            ORDER BY date
            """,
            channel_id,
            year,
            month,
        )

    return [row["date"].isoformat() for row in rows]
