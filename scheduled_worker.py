"""GitHub Actions worker for due recurring Telegram tasks. Uses only configured existing APIs."""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests
import psycopg
from google import genai
from google.genai import types

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


def main():
    # Claim due rows and advance their next-run timestamps in a transaction to avoid duplicates.
    with psycopg.connect(DB) as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT id, user_id, chat_id, request, frequency, local_time, timezone
            FROM agent_schedules
            WHERE enabled=TRUE AND next_run <= NOW()
            ORDER BY next_run
            LIMIT 20
            FOR UPDATE SKIP LOCKED
        """)
        rows = cur.fetchall()
        for ident, user_id, chat_id, request, frequency, local_time, timezone in rows:
            zone = ZoneInfo(timezone)
            now = datetime.now(zone)
            hour, minute = map(int, local_time.split(":"))
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if frequency == "daily":
                next_run += timedelta(days=1)
            else:
                next_run += timedelta(days=7)
            cur.execute(
                "UPDATE agent_schedules SET next_run=%s, last_run=NOW() WHERE id=%s",
                (next_run, ident),
            )
        conn.commit()

    print(f"Claimed {len(rows)} due scheduled task(s).", flush=True)
    for ident, user_id, chat_id, request, frequency, local_time, timezone in rows:
        try:
            result = execute(request)
            send(chat_id, f"Scheduled task #{ident}\n\n{result}")
            print(f"Task {ident} delivered.", flush=True)
        except Exception as exc:
            print(f"Task {ident} failed:", repr(exc), flush=True)
            try:
                send(chat_id, f"Scheduled task #{ident} could not complete this run. Error: {str(exc)[:500]}. It remains scheduled for its next run; no paid fallback was attempted.")
            except Exception as send_exc:
                print(f"Task {ident} failure notice could not be delivered:", repr(send_exc), flush=True)


if __name__ == "__main__":
    main()
