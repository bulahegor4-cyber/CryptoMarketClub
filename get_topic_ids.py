"""Print Telegram forum topic IDs for the configured bot.

Usage:
1. Add TELEGRAM_BOT_TOKEN=... to the project's .env file.
2. In each forum topic, send /topicid to the bot.
3. Run: py get_topic_ids.py

This script only reads pending updates; it does not send messages or trade.
"""
from pathlib import Path
import requests

ENV_PATH = Path(__file__).resolve().parent / ".env"


def read_token():
    with ENV_PATH.open("r", encoding="utf-8-sig") as file:
        for line in file:
            if line.strip().startswith("TELEGRAM_BOT_TOKEN="):
                return line.strip().split("=", 1)[1].strip()
    raise RuntimeError("TELEGRAM_BOT_TOKEN not found in .env")


def main():
    token = read_token()
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    response = requests.get(url, params={"limit": 100, "timeout": 0}, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(payload)

    found = 0
    for update in payload.get("result", []):
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        text = message.get("text", "").strip()
        if not text.startswith("/topicid"):
            continue
        chat = message.get("chat", {})
        thread_id = message.get("message_thread_id")
        if not thread_id:
            print(f"Chat {chat.get('title') or chat.get('username')} ({chat.get('id')}): this is not a forum topic.")
            continue
        print(
            f"Topic: {message.get('forum_topic_created', {}).get('name', 'see topic title in Telegram')}"
            f" | chat_id={chat.get('id')} | message_thread_id={thread_id}"
        )
        found += 1

    if not found:
        print("No /topicid updates found.")
        print("Send /topicid to the bot inside each required forum topic, then run this script again.")
        print("If Telegram reports a webhook conflict, remove the webhook only if this bot is not using one elsewhere.")


if __name__ == "__main__":
    main()
