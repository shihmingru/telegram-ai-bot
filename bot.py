import os
import threading
import google.generativeai as genai
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

app = Flask("telegram_bot")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
   genai.configure(api_key=GEMINI_API_KEY)
   model = genai.GenerativeModel("gemini-2.0-flash")
else:
model = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text("Hello! Send me a message and I will answer.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
if update.message is None:
return


message = update.message.text

if not message:
    return

if model is None:
    await update.message.reply_text("Gemini API key is missing.")
    return

try:
    response = model.generate_content(message)
    await update.message.reply_text(response.text)
except Exception as error:
    print("Gemini error:", error)
    await update.message.reply_text("Sorry, I could not generate a response.")


def run_server():
port = int(os.environ.get("PORT", "10000"))
app.run(host="0.0.0.0", port=port)

def main():
    if not TELEGRAM_BOT_TOKEN:
       print("ERROR: TELEGRAM_BOT_TOKEN is missing.")
return


print("Starting Flask server...")
server = threading.Thread(target=run_server)
server.daemon = True
server.start()

print("Starting Telegram bot...")

application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Telegram bot is running.")
application.run_polling()


main()
