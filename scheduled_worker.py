"""GitHub Actions worker for due recurring Telegram tasks. Uses only configured existing APIs."""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import psycopg
from google import genai
from google.genai import types
from agent_features import due_reminders, mark_reminder_sent, fail_reminder

DB = os.environ["DATABASE_URL"]
TOKEN = os.environ["TELEGRAM_TOKEN"]
KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("GEMINI_MODEL", "").strip() or "gemini-2.5-flash-lite"
client = genai.Client(api_key=KEY)


def send(chat_id, text):
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text[:4000]},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError("Telegram rejected sendMessage")


def retrieve_context(request):
    """Best-effort free public retrieval for requests needing current information."""
    lowered = request.lower()
    keywords = ("news", "latest", "current", "today", "recent", "this week",
                "price", "deadline", "weather", "update", "search", "research",
                "look up", "find online", "what happened")
    if not any(k in lowered for k in keywords):
        return ""
    headers = {"User-Agent": "TelegramPersonalAgent/1.0 (scheduled public-source retrieval)"}
    rss = "https://news.google.com/rss/search?q=" + requests.utils.quote(request) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        import xml.etree.ElementTree as ET
        resp = requests.get(rss, headers=headers, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        rows = []
        for item in root.findall("./channel/item")[:8]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            date = (item.findtext("pubDate") or "").strip()
            if title and link:
                rows.append(f"- {title}\n  URL: {link}\n  Published: {date}")
        if rows:
            return "Live results from Google News RSS (verify source articles):\n" + "\n".join(rows)
    except Exception as exc:
        print("Free news retrieval failed:", repr(exc), flush=True)
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": request,
                    "format": "json", "srlimit": 5},
            headers=headers, timeout=12,
        )
        resp.raise_for_status()
        items = resp.json().get("query", {}).get("search", [])
        if items:
            return "Wikipedia search results (secondary reference, not breaking news):\n" + "\n".join(
                f"- {x.get('title','')}: https://en.wikipedia.org/wiki/{requests.utils.quote(x.get('title','').replace(' ', '_'))}"
                for x in items
            )
    except Exception as exc:
        print("Wikipedia retrieval failed:", repr(exc), flush=True)
    return "No live sources could be retrieved for this run. Be explicit about this and do not present stale knowledge as current."


def execute(request):
    context = retrieve_context(request)
    prompt = (
        "Complete this user's scheduled request as helpfully as possible. This is an automated "
        "recurring task, so produce the result directly rather than asking the user to return later. "
        "Use concise plain text. Never claim an action was taken unless it was. If current information "
        "is needed, rely only on the supplied live retrieval results, cite their URLs, and state clearly "
        "when retrieval failed. Never invent sources or facts. No paid tools or fallbacks are available.\n\n"
        f"Scheduled request:\n{request}\n\n"
        f"Free retrieval context:\n{context or 'No web retrieval was requested by the detector.'}"
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2),
    )
    result = (response.text or "").strip()
    if not result:
        raise RuntimeError("Configured Gemini model returned an empty response")
    return result


def deliver_due_reminders():
    """Deliver due one-shot reminders independently of incoming Telegram messages."""
    try:
        reminders = due_reminders(DB, limit=50)
    except Exception as error:
        print(f"Reminder claim failed ({type(error).__name__}).", flush=True)
        return
    delivered = 0
    for chat_id, message, ident, attempts in reminders:
        try:
            send(chat_id, "Reminder: " + message)
            mark_reminder_sent(DB, ident)
            delivered += 1
        except Exception as error:
            try:
                fail_reminder(DB, ident, type(error).__name__)
            except Exception as db_error:
                print(f"Reminder #{ident} retry state failed ({type(db_error).__name__}).", flush=True)
            print(f"Reminder #{ident} delivery failed ({type(error).__name__}); attempt {attempts}.", flush=True)
    print(f"Delivered {delivered} one-shot reminder(s).", flush=True)


def main():
    # Migrate first, then claim due rows and advance their normal schedule.
    # A retry keeps next_run unchanged and is tracked separately by retry_at.
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE agent_schedules ADD COLUMN IF NOT EXISTS paused BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("ALTER TABLE agent_schedules ADD COLUMN IF NOT EXISTS retry_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE agent_schedules ADD COLUMN IF NOT EXISTS failure_count INTEGER NOT NULL DEFAULT 0")
        cur.execute("ALTER TABLE agent_schedules ADD COLUMN IF NOT EXISTS last_error TEXT")
        cur.execute("""
            SELECT id, user_id, chat_id, request, frequency, local_time, timezone,
                   next_run, retry_at, CASE WHEN next_run <= NOW() THEN 0 ELSE failure_count END AS failure_count, (next_run <= NOW()) AS normal_due
            FROM agent_schedules
            WHERE enabled=TRUE AND paused=FALSE
              AND (next_run <= NOW() OR retry_at <= NOW())
            ORDER BY LEAST(next_run, COALESCE(retry_at, next_run))
            LIMIT 20
            FOR UPDATE SKIP LOCKED
        """)
        rows = cur.fetchall()
        for row in rows:
            ident, user_id, chat_id, request, frequency, local_time, timezone, current_next_run, retry_at, failure_count, normal_due = row
            if normal_due:
                zone = ZoneInfo(timezone)
                now = datetime.now(zone)
                hour, minute = map(int, local_time.split(":"))
                next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1 if frequency == "daily" else 7)
                cur.execute(
                    "UPDATE agent_schedules SET next_run=%s, retry_at=NULL, last_run=NOW(), failure_count=0, last_error=NULL WHERE id=%s",
                    (next_run, ident),
                )
            else:
                # Consume this retry slot before releasing the transaction.
                cur.execute("UPDATE agent_schedules SET retry_at=NULL WHERE id=%s", (ident,))
        conn.commit()

    print(f"Claimed {len(rows)} due scheduled task(s).", flush=True)
    deliver_due_reminders()
    for row in rows:
        ident, user_id, chat_id, request, frequency, local_time, timezone, current_next_run, retry_at, failure_count, normal_due = row
        try:
            result = execute(request)
            send(chat_id, f"Scheduled task #{ident}\\n\\n{result}")
            with psycopg.connect(DB) as conn, conn.cursor() as cur:
                cur.execute(
                    "UPDATE agent_schedules SET failure_count=0, last_error=NULL, retry_at=NULL WHERE id=%s",
                    (ident,),
                )
                conn.commit()
            print(f"Task {ident} delivered.", flush=True)
        except Exception as exc:
            safe_error = type(exc).__name__
            print(f"Task {ident} failed ({type(exc).__name__}).", flush=True)
            # Three total attempts per scheduled occurrence; retry after 15 minutes.
            try:
                with psycopg.connect(DB) as conn, conn.cursor() as cur:
                    cur.execute(
                        """UPDATE agent_schedules
                           SET failure_count=failure_count+1, last_error=%s,
                               retry_at=CASE WHEN failure_count < 2 THEN NOW()+INTERVAL '15 minutes' ELSE NULL END
                           WHERE id=%s""",
                        (safe_error, ident),
                    )
                    conn.commit()
            except Exception as db_error:
                print(f"Task {ident} retry state could not be saved ({type(db_error).__name__}).", flush=True)
            try:
                if failure_count < 2:
                    notice = f"Scheduled task #{ident} failed this run. It will retry after a delay when the worker runs again (three attempts total). No paid fallback was attempted."
                else:
                    notice = f"Scheduled task #{ident} failed after three attempts. Automatic retries for this occurrence have stopped; it remains scheduled for its next regular run. No paid fallback was attempted."
                send(chat_id, notice)
            except Exception as send_exc:
                print(f"Task {ident} failure notice could not be delivered ({type(send_exc).__name__}).", flush=True)


if __name__ == "__main__":
    main()
