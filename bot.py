import os
import threading

from flask import Flask
import google.generativeai as genai

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================
# Environment variables
# =========================

PORT = int(os.environ.get("PORT", "10000"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


# =========================
# Flask web server
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!"


def run_flask():
    print(f"Starting Flask server on port {PORT}")
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


# Start Flask immediately so Render can detect the port.
flask_thread = threading.Thread(
    target=run_flask,
    daemon=True,
)

flask_thread.start()

# =========================
# Check environment
# =========================

print("Environment check:")
print("TELEGRAM_TOKEN exists:", bool(TELEGRAM_TOKEN))
print("GEMINI_API_KEY exists:", bool(GEMINI_API_KEY))
print("PORT:", PORT)

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not available to this process")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not available to this process")

# =========================
# Gemini
# =========================

print("Configuring Gemini...")

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel(
    "gemini-1.5-flash"
)

print("Gemini configured successfully.")


# =========================
# Telegram /start command
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.message.reply_text(
        "Hello! I'm online and ready. Send me a message."
    )


# =========================
# Telegram message handler
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_message = update.message.text

    print("Received:", user_message)

    try:
        response = model.generate_content(user_message)

        reply = response.text

        if reply:
            await update.message.reply_text(reply)
        else:
            await update.message.reply_text(
                "I couldn't generate a response."
            )

    except Exception as error:
        print("Gemini error:", error)

        await update.message.reply_text(
            "Sorry, I encountered an error."
        )


# =========================
# Start Telegram bot
# =========================

def main():
    print("Creating Telegram application...")

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("BOT STARTING")

    application.run_polling()


# =========================
# Entry point
# =========================

if __name__ == "__main__":
    main()

