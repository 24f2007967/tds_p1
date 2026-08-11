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

import json
import time
import os
import base64
import requests

LOG_FILE = "run.jsonl"
LOG_URL = "https://raw.githubusercontent.com/24f2007967/tds_p1/refs/heads/main/run.jsonl"
conversation_history = {}

def push_log_to_github(event):
    token = os.getenv("GITHUB_TOKEN")
    owner = os.getenv("GITHUB_OWNER")
    repo = os.getenv("GITHUB_REPO")
    branch = os.getenv("GITHUB_BRANCH", "main")

    if not token:
        print("ERROR: GITHUB_TOKEN is missing", flush=True)
        return

    if not owner or not repo:
        print("ERROR: GITHUB_OWNER or GITHUB_REPO is missing", flush=True)
        return

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/run.jsonl"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Get the current run.jsonl from GitHub
    response = requests.get(
        url,
        headers=headers,
        params={"ref": branch},
        timeout=15,
    )

    print("GitHub GET:", response.status_code, flush=True)

    if response.status_code == 200:
        data = response.json()

        sha = data["sha"]

        old_content = base64.b64decode(
            data["content"].replace("\n", "")
        ).decode("utf-8")

    elif response.status_code == 404:
        print("run.jsonl does not exist yet", flush=True)

        sha = None
        old_content = ""

    else:
        print("GitHub GET failed:", response.text, flush=True)
        return

    # Add the new event
    new_line = json.dumps(event, ensure_ascii=False) + "\n"

    new_content = old_content + new_line

    # Encode entire updated file
    encoded_content = base64.b64encode(
        new_content.encode("utf-8")
    ).decode("utf-8")

    body = {
        "message": "Update run.jsonl",
        "content": encoded_content,
        "branch": branch,
    }

    # Required when updating an existing file
    if sha:
        body["sha"] = sha

    response = requests.put(
        url,
        headers=headers,
        json=body,
        timeout=15,
    )

    print("GitHub PUT:", response.status_code, flush=True)

    if response.status_code in (200, 201):
        print("SUCCESS: run.jsonl updated", flush=True)
    else:
        print("ERROR: GitHub update failed", flush=True)
        print(response.text, flush=True)


def log_event(event):
    event["timestamp"] = time.time()

    # Keep a local copy too
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

    # Immediately push this event to GitHub
    push_log_to_github(event)

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
