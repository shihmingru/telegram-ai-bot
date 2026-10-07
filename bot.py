import os
import hashlib
import threading

import requests
from flask import Flask, request
import psycopg

from google import genai


# ============================================================
# Environment variables
# ============================================================

PORT = int(os.environ.get("PORT", "10000"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")
RENDER_URL = os.environ.get(
    "RENDER_EXTERNAL_URL",
    "https://telegram-ai-bot-57fa.onrender.com",
)


# ============================================================
# Flask web server
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Personal AI Agent is alive!"


# ============================================================
# Environment check
# ============================================================

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


# ============================================================
# Database
# ============================================================

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


# ============================================================
# Gemini
# ============================================================

print("Configuring Gemini...", flush=True)

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)

print("Gemini configured successfully.", flush=True)


# ============================================================
# Conversation storage
# ============================================================

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
                    (
                        str(user_id),
                        role,
                        content,
                    ),
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
                    (
                        str(user_id),
                        limit,
                    ),
                )

                rows = cursor.fetchall()

        rows.reverse()
        return rows

    except Exception as error:
        print("MEMORY READ ERROR:", repr(error), flush=True)
        return []


# ============================================================
# Telegram helpers
# ============================================================

WEBHOOK_PATH = (
    "/telegram/"
    + hashlib.sha256(TELEGRAM_TOKEN.encode()).hexdigest()[:32]
)

WEBHOOK_URL = RENDER_URL.rstrip("/") + WEBHOOK_PATH

TELEGRAM_API = (
    "https://api.telegram.org/bot"
    + TELEGRAM_TOKEN
)


def send_telegram_message(chat_id, text):
    try:
        response = requests.post(
            TELEGRAM_API + "/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=30,
        )

        response.raise_for_status()

        payload = response.json()

        if not payload.get("ok"):
            raise RuntimeError(payload)

        print(
            "Telegram response sent successfully.",
            flush=True,
        )

    except Exception as error:
        print(
            "TELEGRAM SEND ERROR:",
            repr(error),
            flush=True,
        )


def configure_webhook():
    print("Configuring Telegram webhook...", flush=True)

    try:
        response = requests.post(
            TELEGRAM_API + "/setWebhook",
            json={
                "url": WEBHOOK_URL,
                "drop_pending_updates": True,
            },
            timeout=30,
        )

        response.raise_for_status()

        payload = response.json()

        if not payload.get("ok"):
            raise RuntimeError(payload)

        print(
            "Telegram webhook configured successfully:",
            WEBHOOK_URL,
            flush=True,
        )

    except Exception as error:
        print(
            "TELEGRAM WEBHOOK ERROR:",
            repr(error),
            flush=True,
        )
        raise


# ============================================================
# Message processing
# ============================================================

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
                "Hello! I'm online and ready. "
                "I'm also connected to your private memory system.",
            )
            return

        save_message(
            user_id,
            "user",
            text,
        )

        recent_messages = get_recent_messages(
            user_id,
            limit=10,
        )

        conversation_text = ""

        for role, content in recent_messages:
            if role == "user":
                conversation_text += f"User: {content}\n"
            elif role == "assistant":
                conversation_text += f"Assistant: {content}\n"

        system_instruction = """
You are a calm, kind, compassionate and practical personal AI
companion.

Your role is to help the user with learning, planning,
organization, problem solving, creativity, everyday tasks and
personal growth.

Be warm and supportive without being overly sentimental.

Give clear, practical answers.

When teaching something, prefer step-by-step guidance.

Do not claim to have performed an action unless the application
actually performed it.

Respect the user's privacy.

You are an assistant, not a replacement for qualified
professionals in medical, legal or financial matters.
"""

        prompt = (
            system_instruction
            + "\n\nRecent conversation:\n"
            + conversation_text
            + "\n\nCurrent user message:\n"
            + text
        )

        print("Sending request to Gemini...", flush=True)

        # Gemini can temporarily return 503 when the model is under
        # unusually high demand. Retry transient failures automatically.
        response = None
        last_error = None

        for attempt, delay in enumerate([0, 3, 7, 15], start=1):
            try:
                if delay:
                    print(
                        "Gemini retry " + str(attempt) + "/4 after " + str(delay) + "s...",
                        flush=True,
                    )
                    import time
                    time.sleep(delay)

                response = gemini_client.models.generate_content(
                    model="gemini-3.8-flash",
                    contents=prompt,
                )
                break

            except Exception as error:
                last_error = error
                error_text = repr(error)

                print(
                    "Gemini attempt " + str(attempt) + "/4 failed: " + error_text,
                    flush=True,
                )

                # Retry only transient service-overload/unavailability errors.
                if "503" not in error_text and "UNAVAILABLE" not in error_text:
                    raise

        if response is None:
            raise RuntimeError(
                "Gemini remained unavailable after 4 attempts: "
                + repr(last_error)
            )

        reply = response.text

        if not reply:
            reply = "I couldn't generate a response right now."

        print("Gemini response received.", flush=True)

        save_message(
            user_id,
            "assistant",
            reply,
        )

        send_telegram_message(
            chat_id,
            reply,
        )

    except Exception as error:
        print(
            "MESSAGE PROCESSING ERROR:",
            repr(error),
            flush=True,
        )

        chat_id = (
            update_data.get("message", {})
            .get("chat", {})
            .get("id")
        )

        if chat_id:
            send_telegram_message(
                chat_id,
                "Sorry, I encountered an error while processing "
                "that message.",
            )


# ============================================================
# Telegram webhook endpoint
# ============================================================

@app.route(WEBHOOK_PATH, methods=["POST"])
def telegram_webhook():
    update_data = request.get_json(silent=True) or {}

    print(
        "Telegram webhook received.",
        flush=True,
    )

    worker = threading.Thread(
        target=process_message,
        args=(update_data,),
        daemon=True,
    )

    worker.start()

    return "OK", 200


# ============================================================
# Start
# ============================================================

print("BOT STARTING", flush=True)

configure_webhook()

print(
    "Starting Flask server on port",
    PORT,
    flush=True,
)

app.run(
    host="0.0.0.0",
    port=PORT,
    debug=False,
    use_reloader=False,
)
