import os
import threading
from flask import Flask
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

app = Flask("telegram_bot")

@app.route("/")
def home():
return "Bot is alive!"

def run_flask():
port = int(os.environ.get("PORT", "10000"))
app.run(host="0.0.0.0", port=port)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")
else:
model = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
"Hello! I am your AI bot. Send me a message."
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
if update.message is None:
return


if not update.message.text:
    return

if model is None:
    await update.message.reply_text(
        "Gemini API key is not configured."
    )
    return

try:
    response = model.generate_content(update.message.text)

    if response and response.text:
        await update.message.reply_text(response.text)
    else:
        await update.message.reply_text(
            "I could not generate a response."
        )

except Exception as error:
    print("Gemini error:", error)
    await update.message.reply_text(
        "Sorry, an error occurred while generating the reply."
    )


def main():
print("Starting bot...")


if not TELEGRAM_BOT_TOKEN:
    print("ERROR: TELEGRAM_BOT_TOKEN is missing.")
    return

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is missing.")

flask_thread = threading.Thread(
    target=run_flask,
    daemon=True
)
flask_thread.start()

application = Application.builder().token(
    TELEGRAM_BOT_TOKEN
).build()

application.add_handler(
    CommandHandler("start", start)
)

application.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)

print("Telegram bot is running.")

application.run_polling()


main()
