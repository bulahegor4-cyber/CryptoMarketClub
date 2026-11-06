"""Print Telegram forum topic IDs for the configured bot.

Usage:
1. Add TELEGRAM_BOT_TOKEN=... to the project's .env file.
2. In each forum topic, send /topicid@CryptoMarketClubSignalsBot LABEL (for example: /topicid@CryptoMarketClubSignalsBot signals).
3. Run: py get_topic_ids.py

This script reads pending updates and saves discovered topic IDs to .env; it does not send messages or trade.
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
    discovered = {}
    allowed_labels = {"signals", "news", "altcoins", "macro", "markets", "gold_forex", "psychology", "discussion"}
    for update in payload.get("result", []):
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue
        text = message.get("text", "").strip()
        if not text.startswith("/topicid"):
            continue
        label = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else "UNNAMED"
        chat = message.get("chat", {})
        thread_id = message.get("message_thread_id")
        if not thread_id:
            print(f"{label}: chat_id={chat.get('id')} — not detected inside a forum topic.")
            continue
        print(
            f"{label}: chat_id={chat.get('id')} | message_thread_id={thread_id}"
        )
        if label.lower() in allowed_labels:
            discovered[label.lower()] = int(thread_id)
        else:
            print(f"Label '{label}' ignored. Allowed labels: {', '.join(sorted(allowed_labels))}")
        found += 1

    if discovered:
        lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines()
        for label, thread_id in discovered.items():
            key = f"TELEGRAM_TOPIC_{label.upper()}_ID"
            replacement = f"{key}={thread_id}"
            for index, line in enumerate(lines):
                if line.strip().startswith(key + "="):
                    lines[index] = replacement
                    break
            else:
                lines.append(replacement)
        ENV_PATH.write_text(chr(10).join(lines).rstrip() + chr(10), encoding="utf-8")
        print("Saved topic IDs to .env: " + ", ".join(sorted(discovered)))

    if not found:
        print("No /topicid updates found.")
        print("Send /topicid to the bot inside each required forum topic, then run this script again.")
        print("If Telegram reports a webhook conflict, do not remove the webhook blindly; send the error for review.")


if __name__ == "__main__":
    main()
