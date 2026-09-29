import os
import threading
from flask import Flask
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

PORT = int(os.environ.get("PORT", "10000"))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

app = Flask(name)

def home():
return "Bot is alive!"

app.add_url_rule("/", "home", home)

def run_flask():
app.run(host="0.0.0.0", port=PORT)

if not TELEGRAM_TOKEN:
raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

if not GEMINI_API_KEY:
raise RuntimeError("GEMINI_API_KEY is not set")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text("Hello! I'm online and ready. Send me a message.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
user_message = update.message.text
print("Received:", user_message)

try:
    response = model.generate_content(user_message)
    reply = response.text

    if reply:
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text("I couldn't generate a response.")

except Exception as error:
    print("Gemini error:", error)
    await update.message.reply_text("Sorry, I encountered an error.")

def main():
flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

application = Application.builder().token(TELEGRAM_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("BOT STARTING")
application.run_polling()

if name == "main":
main()
