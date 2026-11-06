from pathlib import Path
from datetime import datetime
import shutil
import py_compile

p = Path("CryptoMarketClub_restored.py")
s = p.read_text(encoding="utf-8")

if "def create_market_heatmap(" in s:
    raise SystemExit("Тепловая карта уже добавлена. Файл не изменён.")

backup = p.with_name(p.name + ".before_heatmap.bak")
shutil.copy2(p, backup)

function_code = r'''

def create_market_heatmap(symbols):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import tempfile

    url = f"{BASE_URL}/openApi/swap/v2/quote/ticker"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"BingX ticker error: {result}")

    by_symbol = {
        item.get("symbol"): item
        for item in result.get("data", [])
    }
    rows = []
    for symbol in symbols:
        item = by_symbol.get(symbol)
        if not item:
            continue
        change = float(item.get("priceChangePercent", 0) or 0)
        price = float(item.get("lastPrice", 0) or 0)
        volume = float(item.get("quoteVolume", 0) or 0)
        rows.append((symbol.replace("-USDT", ""), change, price, volume))

    if not rows:
        raise RuntimeError("No market ticker data for selected symbols")

    rows.sort(key=lambda row: row[1], reverse=True)
    columns = 3
    row_count = (len(rows) + columns - 1) // columns
    fig, ax = plt.subplots(figsize=(12, 3.0 + row_count * 1.7))
    ax.set_xlim(0, columns)
    ax.set_ylim(0, row_count)
    ax.axis("off")

    max_change = max(max(abs(row[1]) for row in rows), 0.1)
    for index, (coin, change, price, volume) in enumerate(rows):
        col = index % columns
        row = row_count - 1 - index // columns
        intensity = min(abs(change) / max_change, 1.0)
        if change >= 0:
            color = (0.12, 0.48 + 0.30 * intensity, 0.28, 1)
        else:
            color = (0.55 + 0.35 * intensity, 0.16, 0.18, 1)

        ax.add_patch(Rectangle(
            (col + 0.04, row + 0.05), 0.92, 0.90,
            facecolor=color, edgecolor="white", linewidth=1.5
        ))
        volume_text = (
            f"{volume / 1e9:.2f}B USDT" if volume >= 1e9
            else f"{volume / 1e6:.1f}M USDT" if volume >= 1e6
            else f"{volume / 1e3:.1f}K USDT"
        )
        ax.text(col + 0.5, row + 0.69, coin,
                ha="center", va="center", color="white",
                fontsize=15, fontweight="bold")
        ax.text(col + 0.5, row + 0.43, f"{change:+.2f}%",
                ha="center", va="center", color="white", fontsize=13)
        ax.text(col + 0.5, row + 0.20,
                f"Price: {price:.6g}\nVol: {volume_text}",
                ha="center", va="center", color="white", fontsize=8)

    fig.suptitle(
        "CryptoMarketClub | Market Heatmap\n"
        + datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        fontsize=15, fontweight="bold"
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    path = str(Path(tempfile.gettempdir()) / "cryptomarketclub_heatmap.png")
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return path

'''

if "def main():" not in s:
    raise SystemExit("Не найдена функция main(); файл не изменён.")

s = s.replace("def main():", function_code + "\ndef main():", 1)

if "    last_news = 0\n" not in s:
    raise SystemExit("Не найден таймер новостей; файл не изменён.")
s = s.replace(
    "    last_news = 0\n",
    "    last_news = 0\n    last_heatmap = 0\n",
    1
)

anchor = "        # A one-second loop keeps the minute schedule responsive without busy-waiting."
heatmap_loop = '''        if now - last_heatmap >= 15 * 60:
            heatmap_path = None
            try:
                heatmap_path = create_market_heatmap(symbols)
                send_telegram_photo(
                    "CryptoMarketClub | Рыночная тепловая карта. "
                    "Цвет показывает изменение цены; объём указан в USDT. "
                    "Это обзор рынка, не гарантия направления цены.",
                    heatmap_path,
                )
                print("Market heatmap sent to Telegram.")
            except Exception as error:
                print("Market heatmap error:", error)
            finally:
                if heatmap_path and os.path.exists(heatmap_path):
                    os.remove(heatmap_path)
            last_heatmap = time.time()

'''
if anchor not in s:
    raise SystemExit("Не найдено место для таймера; файл не изменён.")
s = s.replace(anchor, heatmap_loop + anchor, 1)

p.write_text(s, encoding="utf-8")
try:
    py_compile.compile(str(p), doraise=True)
except Exception:
    shutil.copy2(backup, p)
    raise

print("OK: heatmap added; Python syntax is valid.")
print("Backup:", backup)
print("The bot has NOT been restarted.")
