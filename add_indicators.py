
from pathlib import Path
from datetime import datetime
import py_compile
import shutil
import sys

p = Path("CryptoMarketClub_restored.py")
s = p.read_text(encoding="utf-8")

if "Histogram: {macd_hist" in s:
    print("Telegram message already contains indicators.")
    sys.exit(0)

old = r'        f"EMA20: {ema20:.8g}\nEMA50: {ema50:.8g}\nRSI: {rsi:.1f}\nATR(14): {atr:.8g}\n"'

if s.count(old) != 1:
    print("ERROR: expected message line not found exactly once.")
    print("No changes made.")
    sys.exit(1)

new = old + '\n' + r'        f"MACD: {macd_value:.8g} | Signal: {macd_signal:.8g} | Histogram: {macd_hist:.8g}\\n"' + '\n' + r'        f"Bollinger Bands (20,2): lower={bb_lower:.8g}, middle={bb_mid:.8g}, upper={bb_upper:.8g}\\n"' + '\n' + r'        f"Volume / 20-candle average: {volume_ratio:.2f}x\\n"'

updated = s.replace(old, new, 1)
backup = p.with_name(
    p.name + "." + datetime.now().strftime("%Y%m%d_%H%M%S") + ".bak"
)
temp = Path("_message_check.py")

try:
    temp.write_text(updated, encoding="utf-8")
    py_compile.compile(str(temp), doraise=True)
finally:
    temp.unlink(missing_ok=True)

shutil.copy2(p, backup)
p.write_text(updated, encoding="utf-8")

print("Telegram message updated.")
print("Backup:", backup.name)
print("Syntax check passed.")