import os
import threading
from flask import Flask
import google.generativeai as genai

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# --------------------------------------------------

# Flask web server for Render

# --------------------------------------------------

app = Flask(**name**)

@app.route("/")
def home():
return "Bot is alive!"

def run_flask():
port = int(os.environ.get("PORT", 10000))
app.run(host="0.0.0.0", port=port)

# --------------------------------------------------

# Environment variables

# --------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# --------------------------------------------------

# Gemini setup

# --------------------------------------------------

if GEMINI_API_KEY:
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")
else:
model = None

# --------------------------------------------------

# Telegram commands

# --------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
await update.message.reply_text(
"Hello! 👋\n\n"
"I'm your AI bot. Send me a message and I'll reply."
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
if not update.message or not update.message.text:
return

```
user_message = update.message.text

if model is None:
    await update.message.reply_text(
        "The Gemini API key is not configured on the server."
    )
    return

try:
    response = model.generate_content(user_message)

    if response and response.text:
        await update.message.reply_text(response.text)
    else:
        await update.message.reply_text(
            "Sorry, I couldn't generate a response."
        )

except Exception as e:
    print("Gemini error:", e)
    await update.message.reply_text(
        "Sorry, something went wrong while contacting the AI."
    )
```

# --------------------------------------------------

# Start bot

# --------------------------------------------------

def main():
if not TELEGRAM_BOT_TOKEN:
print("ERROR: TELEGRAM_BOT_TOKEN is not set.")
return

```
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is not set.")

# Start Flask in the background so Render detects the web service port.
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

print("Bot is starting...")

application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

print("Telegram bot is running...")

application.run_polling()
```

if **name** == "**main**":
main()
