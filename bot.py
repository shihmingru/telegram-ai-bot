import os
import hashlib
import threading
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import requests
from flask import Flask, request
import psycopg

from google import genai
from google.genai import types


PORT = int(os.environ.get("PORT", "10000"))  # Render web service

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
RENDER_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://telegram-ai-bot-57fa.onrender.com",
)

app = Flask(__name__)


@app.route("/")
def home():
    return "Personal AI Agent is alive!"


print("Environment check:", flush=True)
print("TELEGRAM_TOKEN exists:", bool(TELEGRAM_TOKEN), flush=True)
print("GEMINI_API_KEY exists:", bool(GEMINI_API_KEY), flush=True)
print("DATABASE_URL exists:", bool(DATABASE_URL), flush=True)
print("PORT:", PORT, flush=True)
print("RENDER_URL:", RENDER_URL, flush=True)

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not available to this process")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not available to this process")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not available to this process")


def test_database():
    print("Testing Supabase PostgreSQL connection...", flush=True)
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                result = cursor.fetchone()
        print("Database connection successful:", result, flush=True)
    except Exception as error:
        print("DATABASE ERROR:", repr(error), flush=True)
        raise


test_database()
print("PASSED DATABASE TEST", flush=True)

print("Configuring Gemini...", flush=True)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
print("Gemini configured successfully.", flush=True)


def discover_gemini_models():
    try:
        available = []
        for model in gemini_client.models.list():
            name = getattr(model, "name", "") or ""
            if name.startswith("models/"):
                name = name[len("models/"):]
            if not name:
                continue
            actions = getattr(model, "supported_actions", None)
            if actions and "generateContent" not in actions:
                continue
            available.append(name)

        available = list(dict.fromkeys(available))
        print(
            "Gemini models available to this API key:",
            ", ".join(available),
            flush=True,
        )

        preferred = [
            "gemini-flash-lite-latest",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.7-flash",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-2.5-flash",
        ]

        ordered = []
        for name in preferred:
            if name in available and name not in ordered:
                ordered.append(name)
        for name in available:
            if "flash" in name.lower() and name not in ordered:
                ordered.append(name)
        for name in available:
            if name not in ordered:
                ordered.append(name)

        if ordered:
            print("Gemini model fallback order:", " -> ".join(ordered), flush=True)
            return ordered

    except Exception as error:
        print("GEMINI MODEL DISCOVERY ERROR:", repr(error), flush=True)

    return ["gemini-3.8-flash"]


GEMINI_MODELS = discover_gemini_models()


class SearchResultParser(HTMLParser):
    """Small dependency-free parser for DuckDuckGo HTML results."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._current_url = None
        self._current_title = []
        self._current_snippet = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()

        if tag == "a" and "result__a" in classes:
            self._current_url = attrs.get("href")
            self._current_title = []
            self._in_title = True

        if self._current_url and "result__snippet" in classes:
            self._current_snippet = []
            self._in_snippet = True

    def handle_endtag(self, tag):
        if tag == "a" and self._in_title and self._current_url:
            title = " ".join("".join(self._current_title).split())
            url = self._normalise_ddg_url(self._current_url)
            if title and url:
                self.results.append(
                    {"title": title, "url": url, "snippet": ""}
                )
            self._in_title = False

        if self._in_snippet:
            self._in_snippet = False

    def handle_data(self, data):
        if self._in_title:
            self._current_title.append(data)
        elif self._in_snippet:
            self._current_snippet.append(data)

    def _normalise_ddg_url(self, href):
        if not href:
            return None
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http://") or href.startswith("https://"):
            return href

        parsed = urlparse(href)
        if parsed.path.startswith("/l/"):
            params = parse_qs(parsed.query)
            target = params.get("uddg", [None])[0]
            if target:
                return unquote(target)
        return None




def web_open(url, max_chars=12000):
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}
    response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "text/html" not in content_type:
        return {"url": response.url, "text": "", "links": []}
    text = _clean_html_text(response.text)[:max_chars]
    parser = HTMLParser()
    links = []
    class LinkCollector(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                href = dict(attrs).get("href")
                if href:
                    link = requests.compat.urljoin(response.url, href)
                    if link.startswith(("http://", "https://")) and link not in links:
                        links.append(link)
    collector = LinkCollector()
    collector.feed(response.text)
    return {"url": response.url, "text": text, "links": links[:100]}


def web_crawl(start_url, max_pages=5):
    root = (urlparse(start_url).hostname or "").lower()
    queue = [start_url]
    visited = set()
    pages = []
    while queue and len(pages) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            page = web_open(url)
            pages.append({"url": page["url"], "text": page["text"]})
            print("Web crawler read page: " + page["url"], flush=True)
            scored = []
            for link in page.get("links", []):
                if (urlparse(link).hostname or "").lower() != root or link in visited:
                    continue
                path = (urlparse(link).path or "").lower()
                score = sum(word in path for word in ("people", "faculty", "profile", "research", "staff", "phd", "directory", "postgraduate"))
                scored.append((score, link))
            scored.sort(reverse=True)
            for _, link in scored:
                if link not in queue:
                    queue.append(link)
        except Exception as error:
            print("Web crawl failed: " + repr(error), flush=True)
    return pages

def _clean_html_text(html):
    class TextParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.skip_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style", "noscript", "svg"}:
                self.skip_depth += 1

        def handle_endtag(self, tag):
            if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
                self.skip_depth -= 1

        def handle_data(self, data):
            if not self.skip_depth:
                value = " ".join(data.split())
                if value:
                    self.parts.append(value)

    parser = TextParser()
    parser.feed(html)
    text = " ".join(parser.parts)
    return re.sub(r"\s+", " ", text).strip()


def _extract_generic_search_results(html, provider, max_results=10):
    """Extract ordinary external links from public search-result HTML."""
    results = []
    seen = set()

    pattern = re.compile(
        r'<a\\b[^>]*href=["\\\']([^"\\\']+)["\\\'][^>]*>(.*?)</a>',
        flags=re.IGNORECASE | re.DOTALL,
    )

    blocked_hosts = {
        "google.com", "www.google.com", "bing.com", "www.bing.com",
        "duckduckgo.com", "www.duckduckgo.com",
    }

    for href, title_html in pattern.findall(html):
        url = unquote(href).strip()
        title = _clean_html_text(title_html)

        if url.startswith("//"):
            url = "https:" + url

        if not url.startswith(("http://", "https://")):
            continue

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if any(host == blocked or host.endswith("." + blocked) for blocked in blocked_hosts):
            continue

        if not title or len(title) < 3 or url in seen:
            continue

        seen.add(url)
        results.append({"title": title[:300], "url": url, "snippet": ""})

        if len(results) >= max_results:
            break

    print(
        provider + " generic extractor found "
        + str(len(results))
        + " external links.",
        flush=True,
    )
    return results


def _academic_faculty_query(query):
    lowered = query.lower()
    academic_terms = [
        "faculty", "professor", "supervisor", "phd", "dphil",
        "buddhist studies", "research areas", "research interests",
        "university", "academic", "remote options",
    ]
    return any(term in lowered for term in academic_terms)


def _fetch_official_academic_sources(query, headers, max_results=5):
    """Fetch known official university directories directly.

    This avoids dependence on public search-engine HTML, which can be
    blocked from cloud hosting. These are primary institutional sources.
    """
    if not _academic_faculty_query(query):
        return []
\n    # Direct official pages are the first browsing targets.\n
    official_pages = [
        ("University of Oxford - AMES people",
         "https://www.ames.ox.ac.uk/people"),
        ("University of Oxford - Theology and Religion people",
         "https://www.theology.ox.ac.uk/people"),
        ("University of Cambridge - AMES people",
         "https://www.ames.cam.ac.uk/people"),
        ("University of Cambridge - Faculty of Divinity directory",
         "https://www.divinity.cam.ac.uk/directory"),
    ]

    results = []
    for title, url in official_pages:
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=8,
                allow_redirects=True,
            )
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type:
                continue

            page_text = _clean_html_text(response.text)
            if not page_text:
                continue

            results.append({
                "title": title,
                "url": response.url,
                "snippet": "Official university directory or people page.",
                "page_text": page_text[:12000],
            })
            print(
                "Official academic source retrieved: " + title,
                flush=True,
            )

            if len(results) >= max_results:
                break

        except Exception as error:
            print(
                "Official academic source failed for "
                + url + ": " + repr(error),
                flush=True,
            )

    return results


def free_web_search(query, max_results=5):
    """Search the public web without an API key or paid search provider."""
    print("Free web search requested:", query, flush=True)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    results = []
    seen = set()

    search_endpoints = [
        ("Mojeek", "https://www.mojeek.com/search", {}),
        ("Yahoo", "https://search.yahoo.com/search", {}),
        ("Google", "https://www.google.com/search", {"gbv": "1"}),
        ("Bing", "https://www.bing.com/search", {}),
        ("DuckDuckGo", "https://html.duckduckgo.com/html/", {}),
    ]

    for provider, endpoint, extra_params in search_endpoints:
        try:
            params = {"q": query}
            params.update(extra_params)

            response = requests.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=8,
            )
            response.raise_for_status()

            candidate_results = []

            parser = SearchResultParser()
            parser.feed(response.text)
            candidate_results.extend(parser.results)

            if not candidate_results:
                candidate_results = _extract_generic_search_results(
                    response.text,
                    provider,
                    max_results=10,
                )

            for item in candidate_results:
                url = item.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                results.append(item)
                if len(results) >= max_results:
                    break

            print(
                provider + " web search returned "
                + str(len(candidate_results))
                + " candidate results.",
                flush=True,
            )

            if results:
                break

        except Exception as error:
            print(
                provider + " web search failed: " + repr(error),
                flush=True,
            )

    if not results:
        print("Free web search returned 0 results.", flush=True)
        return []

    enriched = []
    for item in results[:3]:
        try:
            page = requests.get(
                item["url"],
                headers=headers,
                timeout=6,
                allow_redirects=True,
            )
            content_type = page.headers.get("content-type", "").lower()
            if page.ok and "text/html" in content_type:
                page_text = _clean_html_text(page.text)
                item["page_text"] = page_text[:7000]
            else:
                item["page_text"] = ""
        except Exception as error:
            print(
                "Web page fetch failed for " + item["url"] + ": "
                + repr(error),
                flush=True,
            )
            item["page_text"] = ""
        enriched.append(item)

    return enriched


def query_requires_web(text):
    """Conservative detector for requests whose answer can change over time."""
    lowered = text.lower()

    indicators = [
        "current", "currently", "latest", "today", "tonight", "this week",
        "this month", "this year", "recent", "recently", "updated",
        "up-to-date", "up to date", "as of", "now", "news", "requirements",
        "visa", "price", "prices", "cost", "schedule", "opening hours",
        "weather", "exchange rate", "stock", "deadline", "release date",
        "official source", "official sources", "search the web", "look up",
        "find online", "on the internet", "online", "who is", "what happened",
    ]

    return any(indicator in lowered for indicator in indicators)


def format_web_context(results):
    if not results:
        return ""

    chunks = []
    for index, item in enumerate(results, 1):
        chunks.append(
            "SOURCE " + str(index) + "\n"
            + "Title: " + item.get("title", "") + "\n"
            + "URL: " + item.get("url", "") + "\n"
            + "Search snippet: " + item.get("snippet", "") + "\n"
            + "Page text: " + item.get("page_text", "")
        )
    return "\n\n".join(chunks)


def save_message(user_id, role, content):
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversations
                    (user_id, role, content)
                    VALUES (%s, %s, %s)
                    """,
                    (str(user_id), role, content),
                )
            connection.commit()
    except Exception as error:
        print("MEMORY SAVE ERROR:", repr(error), flush=True)


def get_recent_messages(user_id, limit=10):
    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT role, content
                    FROM conversations
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (str(user_id), limit),
                )
                rows = cursor.fetchall()
        rows.reverse()
        return rows
    except Exception as error:
        print("MEMORY READ ERROR:", repr(error), flush=True)
        return []


WEBHOOK_PATH = "/telegram/" + hashlib.sha256(TELEGRAM_TOKEN.encode()).hexdigest()[:32]
WEBHOOK_URL = RENDER_URL.rstrip("/") + WEBHOOK_PATH
TELEGRAM_API = "https://api.telegram.org/bot" + TELEGRAM_TOKEN


def send_telegram_message(chat_id, text):
    try:
        response = requests.post(
            TELEGRAM_API + "/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(payload)
        print("Telegram response sent successfully.", flush=True)
    except Exception as error:
        print("TELEGRAM SEND ERROR:", repr(error), flush=True)


def configure_webhook():
    print("Configuring Telegram webhook...", flush=True)
    try:
        response = requests.post(
            TELEGRAM_API + "/setWebhook",
            json={
                "url": WEBHOOK_URL,
                "drop_pending_updates": False,
                "allowed_updates": ["message"],
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(payload)

        print("Telegram webhook configured successfully:", WEBHOOK_URL, flush=True)

        info_response = requests.get(
            TELEGRAM_API + "/getWebhookInfo",
            timeout=30,
        )
        info_response.raise_for_status()
        info = info_response.json()

        if info.get("ok"):
            result = info.get("result", {})
            print(
                "Telegram webhook status: "
                + "url=" + str(result.get("url"))
                + ", pending_update_count=" + str(result.get("pending_update_count"))
                + ", last_error_date=" + str(result.get("last_error_date"))
                + ", last_error_message=" + str(result.get("last_error_message")),
                flush=True,
            )
        else:
            print("TELEGRAM WEBHOOK INFO ERROR:", repr(info), flush=True)

    except Exception as error:
        print("TELEGRAM WEBHOOK ERROR:", repr(error), flush=True)
        raise


def process_message(update_data):
    try:
        message = update_data.get("message")
        if not message:
            return

        text = message.get("text")
        chat = message.get("chat")
        user = message.get("from")
        if not text or not chat or not user:
            return

        chat_id = chat.get("id")
        user_id = user.get("id")

        print("Received:", text, flush=True)

        if text.startswith("/start"):
            send_telegram_message(
                chat_id,
                "Hello! I'm online and ready. I'm also connected to your private memory system.",
            )
            return

        save_message(user_id, "user", text)
        recent_messages = get_recent_messages(user_id, limit=10)

        conversation_text = ""
        for role, content in recent_messages:
            if role == "user":
                conversation_text += f"User: {content}\n"
            elif role == "assistant":
                conversation_text += f"Assistant: {content}\n"

        web_required = query_requires_web(text)
        web_results = free_web_search(text) if web_required else []

        if web_required and not web_results:
            reply = (
                "I couldn't complete a live web search for that request right now. "
                "I won't pretend that I searched. Please try again in a moment."
            )
            save_message(user_id, "assistant", reply)
            send_telegram_message(chat_id, reply)
            return

        system_instruction = """
You are a calm, kind, compassionate and practical personal AI
companion.

Your role is to help the user with learning, planning, organization,
problem solving, creativity, everyday tasks and personal growth.

Be warm and supportive without being overly sentimental.
Give clear, practical answers.
When teaching something, prefer step-by-step guidance.
Do not claim to have performed an action unless the application
actually performed it.
Respect the user's privacy.

This application has a separate free web-search layer. When web
research is supplied below, treat those sources as the only evidence
for current or externally verifiable claims. Prefer primary and
official sources. Do not invent facts, citations, page contents, or
search results.

If web research is supplied, answer the user's question using it and
include the relevant source URLs. Clearly distinguish information
supported by the retrieved sources from anything uncertain.

You are an assistant, not a replacement for qualified professionals
in medical, legal or financial matters.
"""

        web_context = ""
        if web_required:
            web_context = (
                "\n\nLIVE WEB RESEARCH RETRIEVED BY THE APPLICATION:\n"
                + format_web_context(web_results)
            )

        prompt = (
            system_instruction
            + "\n\nRecent conversation:\n"
            + conversation_text
            + web_context
            + "\n\nCurrent user message:\n"
            + text
        )

        print("Sending request to Gemini...", flush=True)

        response = None
        last_error = None

        for model_name in GEMINI_MODELS:
            try:
                print("Trying Gemini model: " + model_name, flush=True)
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                print("Gemini response received from " + model_name + ".", flush=True)
                break
            except Exception as error:
                last_error = error
                print(
                    "Gemini model " + model_name + " failed: "
                    + repr(error),
                    flush=True,
                )

        if response is None:
            raise RuntimeError(
                "All discovered Gemini models were unavailable: " + repr(last_error)
            )

        reply = response.text or "I couldn't generate a response right now."
        print("Gemini response received.", flush=True)

        save_message(user_id, "assistant", reply)
        send_telegram_message(chat_id, reply)

    except Exception as error:
        print("MESSAGE PROCESSING ERROR:", repr(error), flush=True)
        chat_id = update_data.get("message", {}).get("chat", {}).get("id")
        if chat_id:
            send_telegram_message(
                chat_id,
                "Sorry, I encountered an error while processing that message.",
            )


@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    update_data = request.get_json(silent=True) or {}

    print("Telegram webhook received.", flush=True)

    worker = threading.Thread(
        target=process_message,
        args=(update_data,),
        daemon=True,
    )
    worker.start()

    return "OK", 200


print("BOT STARTING", flush=True)

# Start Flask first so the public webhook endpoint is accepting requests
# before Telegram is told to deliver updates to it.
def start_server():
    print("Starting Flask server on port", PORT, flush=True)
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# Give Flask a moment to bind the port, then register the webhook.
import time
time.sleep(2)
configure_webhook()

# Keep the main process alive while the Flask thread serves requests.
server_thread.join()
