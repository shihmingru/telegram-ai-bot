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
    """Accept a structured schedule or a natural-language recurring request."""
    source = (text or "").strip()
    structured = re.match(
        r"^\s*(daily|weekly)\s+at\s+(\d{1,2}:\d{2})(?:\s+\[([A-Za-z_/-]+)\])?\s*\|\s*(.+?)\s*$",
        source, re.IGNORECASE
    )
    if structured:
        frequency, clock, timezone, request = structured.groups()
        hour, minute = map(int, clock.split(":"))
        if hour > 23 or minute > 59:
            raise ValueError("Use a valid 24-hour time, such as 08:00 or 19:30.")
        timezone = timezone or DEFAULT_TZ
    else:
        frequency_match = re.search(
            r"\b(every\s+day|each\s+day|daily|every\s+morning|every\s+evening|every\s+week|weekly)\b",
            source, re.IGNORECASE
        )
        time_match = re.search(
            r"\b(?:at\s*)?(?:(2[0-3]|[01]?\d):([0-5]\d)|([1-9]|1[0-2])(?::([0-5]\d))?\s*(am|pm))\b",
            source, re.IGNORECASE
        )
        if not frequency_match or not time_match:
            raise ValueError(
                "Please describe a recurring request and time, for example: "
                "/schedule Every day at 8am, send me the latest AI headlines. "
                "Times default to Taiwan time. You can add [Europe/Paris] to choose a timezone."
            )
        frequency_phrase = frequency_match.group(1).lower()
        frequency = "weekly" if ("week" in frequency_phrase) else "daily"
        if time_match.group(1) is not None:
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
        else:
            hour, minute = int(time_match.group(3)), int(time_match.group(4) or 0)
            if time_match.group(5).lower() == "pm" and hour != 12:
                hour += 12
            elif time_match.group(5).lower() == "am" and hour == 12:
                hour = 0
        clock = f"{hour:02d}:{minute:02d}"
        tz_match = re.search(r"\[([A-Za-z_/-]+)\]", source)
        timezone = tz_match.group(1) if tz_match else DEFAULT_TZ
        request = source
        for match in sorted([frequency_match, time_match] + ([tz_match] if tz_match else []),
                            key=lambda m: m.start(), reverse=True):
            request = request[:match.start()] + " " + request[match.end():]
        request = re.sub(r"^[\s,;:.-]+|[\s,;:.-]+$", "", request)
        request = re.sub(r"(?i)^(?:(?:can|could) you|please|schedule|automate|set up|remind me to|make sure to)\s+", "", request).strip()
        request = re.sub(r"(?i)^(?:and\s+)?(?:then\s+)?", "", request).strip()
        if not request:
            raise ValueError("Please include what you want the bot to do in each run.")
    request = re.sub(r"\s+", " ", request).strip()
    try:
        zone = ZoneInfo(timezone)
    except Exception as exc:
        raise ValueError("That timezone is not recognized. Use a name such as Asia/Taipei or Europe/Paris.") from exc
    if not request or len(request) > 1500:
        raise ValueError("Please include a task request of 1 to 1500 characters.")
    now = datetime.now(zone)
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if due <= now:
        due += timedelta(days=1 if frequency == "daily" else 7)
    return frequency, f"{hour:02d}:{minute:02d}", timezone, request, due


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
