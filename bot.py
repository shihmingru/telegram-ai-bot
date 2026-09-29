```python
import os
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import google.generativeai as genai


# --------------------------------------------------
# 1. Render web server
# --------------------------------------------------

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot is alive!"


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)


# --------------------------------------------------
# 2. Configure Gemini AI
# --------------------------------------------------

gemini_key = os.environ.get("GEMINI_API_KEY", "")

if not gemini_key:
    print("WARNING: GEMINI_API_KEY is not set.")
else:
    genai.configure(api_key=gemini_key)

model = genai.GenerativeModel("gemini-1.5-flash")


# --------------------------------------------------
# 3. Test Telegram connection
# --------------------------------------------------

def test_telegram_connection():
    token = os.environ.get("TELEGRAM_TOKEN", "")

    print("Testing Telegram connection...")

    if not token:
        print("ERROR: TELEGRAM_TOKEN is not set.")
        return

    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        )

        print("Telegram HTTP status:", response.status_code)

        # Do NOT print the token.
        print("Telegram response:", response.text)

    except Exception as e:
        print("Telegram connection error:", repr(e))


# --------------------------------------------------
# 4. Telegram commands
# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! I am your free cloud-hosted AI Agent. "
        "Ask me anything!"
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user_text = update.message.text

    try:
        response = model.generate_content(user_text)

        if response.text:
            await update.message.reply_text(response.text)
        else:
            await update.message.reply_text(
                "I couldn't generate a response."
            )

    except Exception as e:
        print("Gemini error:", repr(e))
        await update.message.reply_text(
            "Sorry, I encountered an error while processing your message."
        )


# --------------------------------------------------
# 5. Start everything
# --------------------------------------------------

def main():
    print("Bot is starting...")

    # Test Telegram before starting the bot.
    test_telegram_connection()

    # Start Render's web server in the background.
    threading.Thread(
        target=run_flask,
        daemon=True,
    ).start()

    # Get Telegram token.
    token = os.environ.get("TELEGRAM_TOKEN", "")

    if not token:
        print("ERROR: TELEGRAM_TOKEN is missing.")
        return

    # Build Telegram application.
    application = (
        Application.builder()
        .token(token)
        .build()
    )

    # Add handlers.
    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )

    print("Telegram bot is starting polling...")

    application.run_polling()


if __name__ == "__main__":
    main()
```
