

from pathlib import Path

file_path = Path("CryptoMarketClub_restored.py")
backup_path = Path("CryptoMarketClub_topics_backup.py")

if not backup_path.exists():
    raise SystemExit("ОШИБКА: резервная копия не найдена.")

code = file_path.read_text(encoding="utf-8")

if 'CHAT_ID = "669952449"' not in code:
    raise SystemExit("ОШИБКА: исходный CHAT_ID не найден.")

# Заменяем текстовую функцию по границам def, не затрагивая текст ошибки.
start = code.find("def send_telegram(message):")
end = code.find("\ndef ema(", start)
if start == -1 or end == -1:
    raise SystemExit("ОШИБКА: не найдена функция send_telegram.")

new_text_function = '''def send_telegram(message, thread_id=None):
    token = get_token()
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram sendMessage failed")


'''
code = code[:start] + new_text_function + code[end + 1:]

# Маршруты для сигналов.
mode_line = '    for mode_name, timeframes in modes:\n'
if code.count(mode_line) != 1:
    raise SystemExit("ОШИБКА: не найден единственный цикл scan_modes.")

code = code.replace(
    mode_line,
    mode_line + '''        topic_id = {
            "SCALPING": 3,
            "MEDIUM-TERM": 5,
            "LONG-TERM": 6,
            "DAILY": 6,
        }.get(mode_name)
''',
    1,
)

if code.count('send_telegram_photo(signal["message"], chart_path)') != 1:
    raise SystemExit("ОШИБКА: вызов отправки графика не найден.")
if code.count('send_telegram(signal["message"])') != 1:
    raise SystemExit("ОШИБКА: вызов отправки сигнала не найден.")
if code.count('send_telegram(message[:4000])') != 1:
    raise SystemExit("ОШИБКА: вызов отправки новости не найден.")

code = code.replace(
    'send_telegram_photo(signal["message"], chart_path)',
    'send_telegram_photo(signal["message"], chart_path, thread_id=topic_id)',
    1,
)
code = code.replace(
    'send_telegram(signal["message"])',
    'send_telegram(signal["message"], thread_id=topic_id)',
    1,
)
code = code.replace(
    'send_telegram(message[:4000])',
    'send_telegram(message[:4000], thread_id=13)',
    1,
)

# Обновляем отправку фотографий.
start = code.find("def send_telegram_photo(message, image_path):")
end = code.find("\ndef create_market_heatmap(", start)
if start == -1 or end == -1:
    raise SystemExit("ОШИБКА: границы функции отправки фото не найдены.")

new_photo_function = '''def send_telegram_photo(message, image_path, thread_id=None):
    token = get_token()
    with open(image_path, "rb") as photo:
        data = {
            "chat_id": CHAT_ID,
            "caption": message[:1024],
        }
        if thread_id is not None:
            data["message_thread_id"] = thread_id
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=data,
            files={"photo": photo},
            timeout=30,
        )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram sendPhoto failed")


'''
code = code[:start] + new_photo_function + code[end + 1:]

# Направляем HEATMAP в тему 4.
heatmap_old = '''                    heatmap_path,
                )'''
if code.count(heatmap_old) != 1:
    raise SystemExit("ОШИБКА: вызов HEATMAP не найден однозначно.")

code = code.replace(
    heatmap_old,
    '''                    heatmap_path,
                    thread_id=4,
                )''',
    1,
)

# Меняем ID группы только после всех проверок.
code = code.replace(
    'CHAT_ID = "669952449"',
    'CHAT_ID = "-1004357087660"',
    1,
)

file_path.write_text(code, encoding="utf-8")
print("Изменения сохранены.")

