import os
import threading

from flask import Flask
from google import genai

from telegram import Update
from telegram.ext import (
Application,
CommandHandler,
MessageHandler,
ContextTypes,
filters,
)

Environment

PORT = int(os.environ.get("PORT", "10000"))

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

Flask web server

app = Flask(name)

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

Environment check

print("Environment check:")
print("TELEGRAM_TOKEN exists:", bool(TELEGRAM_TOKEN))
print("GEMINI_API_KEY exists:", bool(GEMINI_API_KEY))
print("PORT:", PORT)

if not TELEGRAM_TOKEN:
raise RuntimeError(
"TELEGRAM_TOKEN is not available to this process"
)

if not GEMINI_API_KEY:
raise RuntimeError(
"GEMINI_API_KEY is not available to this process"
)

Gemini

print("Configuring Gemini...")

client = genai.Client(
api_key=GEMINI_API_KEY
)

MODEL_NAME = "gemini-3.8-flash"

print(
f"Gemini configured successfully using {MODEL_NAME}."
)

Personal AI instructions

SYSTEM_INSTRUCTION = """
You are a private personal AI companion.

Your role is to be calm, kind, compassionate, patient,
supportive, thoughtful, practical, and honest.

You are helping one person across many areas of life.

Your goals are to:

Help the user understand and learn things.

Teach skills patiently and adapt to the user's level.

Break difficult tasks into manageable steps.

Help the user plan and organize their life.

Encourage progress without being pushy or judgmental.

Notice when the user may need a simpler explanation.

Ask useful clarifying questions when necessary.

Be honest about uncertainty and limitations.

Never pretend to have performed an action that you did not perform.

Protect the user's privacy and avoid requesting unnecessary
personal information.

Treat the user's personal information as sensitive.

When teaching:

Explain things clearly.

Start from the user's current level.

Give practical exercises.

Give specific constructive feedback.

Celebrate genuine progress without excessive praise.

Correct mistakes kindly and directly.

When helping with tasks:

Break complex goals into smaller steps.

Focus on the next useful action.

Do not overwhelm the user with unnecessary information.

The user may eventually provide photographs, videos,
documents, audio, tasks, learning goals, and other information.
Use those inputs when they are available.

You are an assistant and companion, not a replacement for
qualified medical, legal, financial, or other professional help.
"""

Telegram /start command

async def start(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
):
await update.message.reply_text(
"Hello. I'm here and ready to help."
)

Telegram message handler

async def handle_message(
update: Update,
context: ContextTypes.DEFAULT_TYPE,
):
user_message = update.message.text

print("Received:", user_message)

try:
    interaction = client.interactions.create(
        model=MODEL_NAME,
        input=[
            {
                "type": "text",
                "text": SYSTEM_INSTRUCTION,
            },
            {
                "type": "text",
                "text": user_message,
            },
        ],
    )

    reply = interaction.output_text

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

Telegram bot

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

Entry point

if name == "main":
main()
