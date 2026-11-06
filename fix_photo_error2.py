from pathlib import Path

p = Path("CryptoMarketClub_restored.py")
s = p.read_text(encoding="utf-8")
start = s.index("def send_telegram_photo(")
end = s.index("def create_market_heatmap(", start)
part = s[start:end]
part = part.replace(
    next(line for line in part.splitlines() if "raise RuntimeError(" in line),
    '        raise RuntimeError("Telegram не принял изображение")'
)
p.write_text(s[:start] + part + s[end:], encoding="utf-8")
print("Текст ошибки в send_telegram_photo исправлен.")
