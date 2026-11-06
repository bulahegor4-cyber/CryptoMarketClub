from pathlib import Path
from datetime import datetime
import ast
import shutil
import sys

folder = Path(__file__).resolve().parent
target = folder / "listing_scanner.py"
source = target.read_text(encoding="utf-8")

anchor = '                message = ('
rating_block = '''                total_volume = sum(
                    volume for volume in exchange_volumes.values() if volume > 0
                )

                if total_volume >= 1_000_000:
                    volume_rating = "🟢 Высокий"
                elif total_volume >= 100_000:
                    volume_rating = "🟡 Средний"
                elif total_volume > 0:
                    volume_rating = "🔴 Низкий"
                else:
                    volume_rating = "⚪ Нет данных"

'''

if source.count(anchor) != 1:
    print("Блок сообщения неоднозначен. Файл не изменён.")
    sys.exit(1)

if "volume_rating" in source:
    print("Оценка уже присутствует. Файл не изменён.")
    sys.exit(1)

updated = source.replace(anchor, rating_block + anchor, 1)

line = '                    f"Бирж с доступным объёмом: {active_exchanges}\\n"'
if updated.count(line) != 1:
    print("Строка не совпала. Файл не изменён.")
    sys.exit(1)

replacement = (
    '                    f"Суммарный объём за 24 ч.: {total_volume:,.0f} USDT\\n"\n'
    '                    f"Оценка объёма: {volume_rating}\\n"\n'
    + line
)
updated = updated.replace(line, replacement, 1)

try:
    ast.parse(updated)
except SyntaxError as error:
    print(f"Проверка синтаксиса не пройдена: {error}")
    print("Файл не изменён.")
    sys.exit(1)

backup = folder / (
    "listing_scanner_before_rating_" +
    datetime.now().strftime("%Y%m%d_%H%M%S") + ".py"
)
shutil.copy2(target, backup)
target.write_text(updated, encoding="utf-8")

print("Оценка объёма успешно добавлена.")
print("Резервная копия:", backup.name)
print("Синтаксис проверен; сканер не запускался.")