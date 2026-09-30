import os
import threading

from flask import Flask
import psycopg

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google import genai


# ============================================================
# Environment variables
# ============================================================

PORT = int(os.environ.get("PORT", "10000"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")


# ============================================================
# Flask web server
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Personal AI Agent is alive!"


def run_flask():
    print(f"Starting Flask server on port {PORT}")

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


flask_thread = threading.Thread(
    target=run_flask,
    daemon=True,
)

flask_thread.start()


# ============================================================
# Environment check
# ============================================================

print("Environment check:")
print("TELEGRAM_TOKEN exists:", bool(TELEGRAM_TOKEN))
print("GEMINI_API_KEY exists:", bool(GEMINI_API_KEY))
print("DATABASE_URL exists:", bool(DATABASE_URL))
print("PORT:", PORT)


if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "TELEGRAM_TOKEN is not available to this process"
    )


if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not available to this process"
    )


if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not available to this process"
    )


# ============================================================
# Database
# ============================================================

def test_database():
    print("Testing Supabase PostgreSQL connection...")

    try:
        with psycopg.connect(DATABASE_URL) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                result = cursor.fetchone()

        print("Database connection successful:", result)

    except Exception as error:
        print("DATABASE ERROR:", error)
        raise


test_database()


# ============================================================
# Gemini
# ============================================================

print("Configuring Gemini...")

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)

print("Gemini configured successfully.")


# ============================================================
# Save conversation
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
        print("MEMORY SAVE ERROR:", error)


# ============================================================
# Get recent conversation
# ============================================================

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
        print("MEMORY READ ERROR:", error)
        return []


# ============================================================
# /start command
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "Hello! I'm online and ready. "
        "I'm also connected to your private memory system."
    )


# ============================================================
# Telegram message handler
# ============================================================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_message = update.message.text
    user_id = update.effective_user.id

    print("Received:", user_message)

    # --------------------------------------------------------
    # Save user's message
    # --------------------------------------------------------

    save_message(
        user_id,
        "user",
        user_message,
    )

    # --------------------------------------------------------
    # Retrieve recent conversation
    # --------------------------------------------------------

    recent_messages = get_recent_messages(
        user_id,
        limit=10,
    )

    # --------------------------------------------------------
    # Build conversation context
    # --------------------------------------------------------

    conversation_text = ""

    for role, content in recent_messages:

        if role == "user":
            conversation_text += (
                f"User: {content}\n"
            )

        elif role == "assistant":
            conversation_text += (
                f"Assistant: {content}\n"
            )

    # --------------------------------------------------------
    # System instruction
    # --------------------------------------------------------

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
        + user_message
    )

    # --------------------------------------------------------
    # Ask Gemini
    # --------------------------------------------------------

    try:

        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        reply = response.text

        if not reply:
            reply = (
                "I couldn't generate a response right now."
            )

        # ----------------------------------------------------
        # Save assistant response
        # ----------------------------------------------------

        save_message(
            user_id,
            "assistant",
            reply,
        )

        await update.message.reply_text(reply)

    except Exception as error:

        print("Gemini error:", error)

        await update.message.reply_text(
            "Sorry, I encountered an error while processing "
            "that message."
        )


# ============================================================
# Start Telegram bot
# ============================================================

def main():

    print("Creating Telegram application...")

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("BOT STARTING")

    application.run_polling()


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    main()
