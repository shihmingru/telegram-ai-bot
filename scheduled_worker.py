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
    """Retrieve current news from free RSS feeds, with independent source fallbacks."""
    import email.utils
    import xml.etree.ElementTree as ET
    from datetime import timezone as dt_timezone

    lowered = request.lower()
    keywords = ("news", "latest", "current", "today", "recent", "this week",
                "price", "deadline", "weather", "update", "search", "research",
                "look up", "find online", "what happened")
    if not any(k in lowered for k in keywords):
        return ""

    headers = {"User-Agent": "Mozilla/5.0 (compatible; TelegramPersonalAgent/1.1; RSS reader)"}
    is_regional_briefing = (
        "daily news" in lowered
        or ("singapore" in lowered and "france" in lowered and "taiwan" in lowered)
    )

    def parse_feed(content):
        root = ET.fromstring(content)
        entries = root.findall("./channel/item")
        if not entries:
            entries = [e for e in root.iter() if e.tag.rsplit("}", 1)[-1] == "entry"]
        output = []
        cutoff = datetime.now(dt_timezone.utc) - timedelta(hours=48)
        seen = set()
        for item in entries:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not link:
                link_node = next((e for e in item if e.tag.rsplit("}", 1)[-1] == "link"), None)
                if link_node is not None:
                    link = (link_node.attrib.get("href") or link_node.text or "").strip()
            published = (item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date")
                         or item.findtext("{http://www.w3.org/2005/Atom}updated")
                         or item.findtext("{http://www.w3.org/2005/Atom}published") or "").strip()
            if not title or not link or title.casefold() in seen:
                continue
            # Reject old or undated entries rather than presenting them as current news.
            try:
                dt = email.utils.parsedate_to_datetime(published)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=dt_timezone.utc)
                if dt.astimezone(dt_timezone.utc) < cutoff:
                    continue
            except (TypeError, ValueError, OverflowError):
                continue
            seen.add(title.casefold())
            output.append((dt, title, link, published))
            if len(output) >= 12:
                break
        output.sort(key=lambda row: row[0], reverse=True)
        return output

    def collect_region(region, sources, limit=3):
        failures = []
        for label, url, params in sources:
            try:
                response = requests.get(url, params=params, headers=headers, timeout=10)
                response.raise_for_status()
                rows = parse_feed(response.content)
                if rows:
                    return region + " (source: " + label + "):\\n" + "\\n".join(
                        f"- {title}\\n  URL: {link}\\n  Published: {published}"
                        for _, title, link, published in rows[:limit]
                    )
                failures.append(label + ": no recent dated entries")
            except Exception as exc:
                failures.append(label + ": " + type(exc).__name__)
        print("RSS retrieval unavailable for " + region + " (" + "; ".join(failures) + ").", flush=True)
        return region + ": No live news sources could be retrieved for this run."

    google = "https://news.google.com/rss/search"
    if is_regional_briefing:
        feeds = [
            ("Singapore (SG)", [
                ("CNA Singapore RSS", "https://www.channelnewsasia.com/api/v1/rss-outbound-feed", {"_format":"xml","category":"10416"}),
                ("Google News Singapore", google, {"q":"Singapore news when:2d","hl":"en-SG","gl":"SG","ceid":"SG:en"}),
            ]),
            ("France (FR)", [
                ("France 24 France RSS", "https://www.france24.com/en/france/rss", {}),
                ("Google News France", google, {"q":"France news when:2d","hl":"en-US","gl":"US","ceid":"US:en"}),
            ]),
            ("Taiwan (TW)", [
                ("Google News Taiwan", google, {"q":"Taiwan news when:2d","hl":"en-US","gl":"US","ceid":"US:en"}),
                ("Taiwan News RSS", "https://www.taiwannews.com.tw/rss", {}),
                ("BBC Asia RSS", "https://feeds.bbci.co.uk/news/world/asia/rss.xml", {}),
            ]),
            ("Global", [
                ("BBC World RSS", "https://feeds.bbci.co.uk/news/world/rss.xml", {}),
                ("Deutsche Welle RSS", "https://rss.dw.com/xml/rss-en-all", {}),
                ("Google News World", google, {"q":"world news when:2d","hl":"en-US","gl":"US","ceid":"US:en"}),
            ]),
        ]
        sections = [collect_region(region, sources) for region, sources in feeds]
        return (
            "Live RSS news results. Headlines are sourced from the listed feeds and are not independently fact-checked. "
            "Only headlines with publication timestamps within the last 48 hours are included. Do not invent updates; "
            "if retrieval fails for a region, report that explicitly.\\n\\n" + "\\n\\n".join(sections)
        )

    rows = collect_region("Current news", [
        ("Google News search", google, {"q":request + " when:2d","hl":"en-US","gl":"US","ceid":"US:en"}),
        ("BBC World RSS", "https://feeds.bbci.co.uk/news/world/rss.xml", {}),
        ("Deutsche Welle RSS", "https://rss.dw.com/xml/rss-en-all", {}),
    ], limit=8)
    if "No live news sources could be retrieved" in rows:
        return "No live news sources could be retrieved for this run. State this clearly and do not substitute stale knowledge or unrelated reference pages for current news."
    return "Live RSS results (use the listed source URLs; not independently fact-checked):\\n" + rows


def execute(request, user_id=None):
    """Run the saved instruction through the same bounded tool-using agent as live chats."""
    # Import lazily to avoid a module-import cycle: bot.py imports this worker inside its poll loop.
    import bot
    prompt = (
        "Execute this user's scheduled task now using the available agent tools. "
        "Treat this as the scheduled occurrence, not as a request to explain how to do it. "
        "Use the tools required to complete the task when they are available. "
        "For current information, retrieve live sources and include their URLs; if retrieval fails, "
        "say so clearly and do not substitute stale knowledge. Do not claim an action succeeded unless "
        "the tool confirms it. Do not bypass approvals for external changes. If the task cannot be completed "
        "with available tools or permissions, state the exact limitation briefly.\n\n"
        "Scheduled task:\n" + request
    )
    return bot.run_agent(prompt, user_id=user_id)


def deliver_free_news_schedules():
    """Deliver due news schedules from free RSS feeds without calling Gemini."""
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("ALTER TABLE agent_schedules ADD COLUMN IF NOT EXISTS paused BOOLEAN NOT NULL DEFAULT FALSE")
        cur.execute("""
            SELECT id, chat_id, request, frequency, local_time, timezone
            FROM agent_schedules
            WHERE enabled=TRUE AND paused=FALSE
              AND (next_run <= NOW() OR retry_at <= NOW())
              AND request ~* '(news|headlines)'
            ORDER BY next_run
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        rows = cur.fetchall()
        for ident, chat_id, request, frequency, local_time, timezone in rows:
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
        conn.commit()

    for ident, chat_id, request, frequency, local_time, timezone in rows:
        try:
            result = retrieve_context(request)
            if not result:
                result = "No live RSS retrieval was available for this scheduled news request."
            send(chat_id, f"Scheduled task #{ident}\\n\\n{result}")
            print(f"Free RSS news task {ident} delivered.", flush=True)
        except Exception as error:
            print(f"Free RSS news task {ident} failed ({type(error).__name__}).", flush=True)


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
            result = execute(request, user_id=user_id)
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
