import json
import time
import os
import subprocess

from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AIPIPE_TOKEN = os.getenv("AIPIPE_TOKEN")
LOG_URL = "https://raw.githubusercontent.com/24f2007967/tds_p1/refs/heads/main/run.jsonl"
# -----------------------------
PORT = int(os.environ.get("PORT", 10000))
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
client = OpenAI(
    base_url="https://aipipe.org/openai/v1",
    api_key=AIPIPE_TOKEN,
)

LOG_FILE = "run.jsonl"

# Push to GitHub every 5 log entries
PUSH_EVERY = 5
log_counter = 0

conversation_history = {}


import os
import base64
import requests

def push_log_to_github():
    token = os.getenv("GITHUB_TOKEN")
    owner = os.getenv("GITHUB_OWNER")
    repo = os.getenv("GITHUB_REPO")
    branch = os.getenv("GITHUB_BRANCH", "main")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/run.jsonl"

    # Get current file SHA
    response = requests.get(url, headers=headers, params={"ref": branch})

    sha = None
    if response.status_code == 200:
        sha = response.json()["sha"]

    with open("run.jsonl", "rb") as f:
        content = base64.b64encode(f.read()).decode()

    body = {
        "message": "Update run.jsonl",
        "content": content,
        "branch": branch,
    }

    if sha:
        body["sha"] = sha

    r = requests.put(url, headers=headers, json=body)

    if r.status_code in (200, 201):
        print("GitHub updated successfully")
    else:
        print("GitHub upload failed")
        print(r.status_code)
        print(r.text)


def log_event(event: dict):
    global log_counter

    event["timestamp"] = time.time()

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    log_counter += 1

    if log_counter >= PUSH_EVERY:
        push_log_to_github()
        log_counter = 0


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    log_event({
        "type": "incoming",
        "chat_id": chat_id,
        "text": user_text
    })

    history = conversation_history.setdefault(chat_id, [])
    history.append({
        "role": "user",
        "content": user_text
    })

    system_prompt = (
        "You are a careful data analyst. The user's LAST message asks a data-analysis "
        "question and tells you exactly what JSON shape to reply with. Work out the "
        "real answer. Reply with ONLY the required JSON object and nothing else."
    )

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            *history[-6:]
        ],
    )

    reply_text = response.choices[0].message.content.strip()
    history.append({
        "role": "assistant",
        "content": reply_text
    })

    try:
        parsed = json.loads(reply_text)
    except json.JSONDecodeError:
        start = reply_text.find("{")
        end = reply_text.rfind("}")
        parsed = json.loads(reply_text[start:end + 1])

    parsed["log_url"] = LOG_URL
    final_reply = json.dumps(parsed)

    log_event({
        "type": "outgoing",
        "chat_id": chat_id,
        "text": final_reply
    })

    await update.message.reply_text(final_reply)

app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

app.add_handler(
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)

print("Starting webhook...")

app.run_webhook(
    listen="0.0.0.0",
    port=PORT,
    url_path=TELEGRAM_BOT_TOKEN,
    webhook_url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}",
)
