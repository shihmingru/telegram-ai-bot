import os
import threading
from flask import Flask
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

PORT = int(os.environ.get("PORT", 10000))

app = Flask(name)

@app.route("/")
def home():
return "Bot is alive!"

def run_flask():
app.run(host="0.0.0.0", port=PORT)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not TELEGRAM_TOKEN:
raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

if not GEMINI_API_KEY:
raise RuntimeError("GEMINI_API_KEY is not set")

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-1.5-flash")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
"Hello! I'm online and ready. Send me a message."
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
try:
user_message = update.message.text


    response = model.generate_content(user_message)

    if response.text:
        await update.message.reply_text(response.text)
    else:
        await update.message.reply_text(
            "Sorry, I couldn't generate a response."
        )

except Exception as e:
    print(f"ERROR: {e}")
    await update.message.reply_text(
        "Sorry, something went wrong while processing your message."
    )


def main():
threading.Thread(target=run_flask, daemon=True).start()


application = Application.builder().token(TELEGRAM_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

print("Bot is starting...")
application.run_polling()


if name == "main":
main()
