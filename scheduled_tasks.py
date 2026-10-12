"""Persistent recurring tasks shared by the Telegram bot and GitHub Actions worker."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import psycopg

DEFAULT_TZ = "Asia/Taipei"


def ensure_schedule_table(db):
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_schedules (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                request TEXT NOT NULL,
                frequency TEXT NOT NULL CHECK (frequency IN ('daily', 'weekly')),
                local_time TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Taipei',
                next_run TIMESTAMPTZ NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_run TIMESTAMPTZ
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS agent_schedules_due_idx ON agent_schedules(next_run) WHERE enabled = TRUE")
        conn.commit()


def parse_schedule_text(text):
    """Parse /schedule daily at 08:00 | request, or weekly at 09:30 | request."""
    match = re.match(
        r"^\s*(daily|weekly)\s+at\s+(\d{1,2}:\d{2})(?:\s+\[([A-Za-z_/-]+)\])?\s*\|\s*(.+?)\s*$",
        text or "", re.IGNORECASE
    )
    if not match:
        raise ValueError(
            "Use /schedule daily at 08:00 | your task, or /schedule weekly at 09:30 | your task. "
            "Times default to Taiwan time. To choose a timezone, add it in square brackets before |, "
            "for example /schedule daily at 08:00 [Europe/Paris] | your task."
        )
    frequency, clock, timezone, request = match.groups()
    hour, minute = map(int, clock.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("Use a valid 24-hour time, such as 08:00 or 19:30.")
    timezone = timezone or DEFAULT_TZ
    try:
        zone = ZoneInfo(timezone)
    except Exception as exc:
        raise ValueError("That timezone is not recognized. Use a name such as Asia/Taipei or Europe/Paris.") from exc
    if len(request) > 1500:
        raise ValueError("Keep the scheduled request under 1500 characters.")
    now = datetime.now(zone)
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now:
        due += timedelta(days=1 if frequency.lower() == "daily" else 7)
    if frequency.lower() == "weekly" and due <= now:
        due += timedelta(days=7)
    # If the selected weekly time is later today, the first run should be today,
    # then every seven days. Otherwise the calculation above chooses next week.
    if frequency.lower() == "weekly" and due.date() == now.date() and due <= now:
        due += timedelta(days=7)
    return frequency.lower(), f"{hour:02d}:{minute:02d}", timezone, request, due


def add_schedule(db, user_id, chat_id, text):
    frequency, clock, timezone, request, due = parse_schedule_text(text)
    ensure_schedule_table(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO agent_schedules
               (user_id, chat_id, request, frequency, local_time, timezone, next_run)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (str(user_id), str(chat_id), request, frequency, clock, timezone, due)
        )
        ident = cur.fetchone()[0]
        conn.commit()
    return ident, frequency, clock, timezone, request, due


def list_schedules(db, user_id):
    ensure_schedule_table(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id, request, frequency, local_time, timezone, next_run
               FROM agent_schedules WHERE user_id=%s AND enabled=TRUE ORDER BY id DESC LIMIT 50""",
            (str(user_id),)
        )
        return cur.fetchall()


def cancel_schedule(db, user_id, ident):
    ensure_schedule_table(db)
    with psycopg.connect(db) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE agent_schedules SET enabled=FALSE WHERE id=%s AND user_id=%s AND enabled=TRUE",
            (int(ident), str(user_id))
        )
        changed = cur.rowcount == 1
        conn.commit()
        return changed
