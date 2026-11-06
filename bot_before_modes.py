import requests
import time
import os
import hashlib
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

BASE_URL = "https://open-api.bingx.com"
CHAT_ID = "669952449"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
SEEN_NEWS_PATH = os.path.join(SCRIPT_DIR, "seen_news.txt")
SCAN_INTERVAL_SECONDS = 15 * 60

NEWS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/?outputType=xml"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("The Block", "https://www.theblock.co/rss.xml"),
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
]

# Keyword-based first-pass classification. This is not an AI model and can be wrong.
HIGH_IMPACT_TERMS = [
    "sec", "lawsuit", "court", "ban", "banned", "approval", "approved",
    "etf", "hack", "hacked", "exploit", "breach", "bankruptcy", "insolvency",
    "fed", "federal reserve", "interest rate", "rate cut", "rate hike",
    "inflation", "cpi", "jobs report", "recession", "sanction", "war",
    "liquidation", "liquidations", "outage", "stablecoin", "depeg",
    "default", "investigation", "settlement", "bitcoin reserve",
]
POSITIVE_TERMS = [
    "approved", "approval", "inflows", "adoption", "partnership", "launch",
    "record high", "surge", "rally", "rate cut", "bullish", "buy",
    "accumulation", "integration", "wins", "settlement reached",
]
NEGATIVE_TERMS = [
    "hack", "hacked", "exploit", "breach", "lawsuit", "ban", "banned",
    "outflows", "crash", "plunge", "sell-off", "bearish", "fraud",
    "bankruptcy", "insolvency", "depeg", "arrested", "charges", "rate hike",
]
COIN_TERMS = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "ether", "eth"],
    "SOL": ["solana", "sol"],
    "BNB": ["bnb", "binance"],
    "XRP": ["xrp", "ripple"],
    "DOGE": ["dogecoin", "doge"],
    "ADA": ["cardano", "ada"],
    "LINK": ["chainlink", "link"],
    "AVAX": ["avalanche", "avax"],
    "PUMP": ["pump.fun", "pump token", "pump crypto"],
    "LTC": ["litecoin", "ltc"],
}


def get_token():
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.strip().split("=", 1)[1]
    raise ValueError("Токен не найден в .env")


def send_telegram(message):
    token = get_token()
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": CHAT_ID, "text": message, "disable_web_page_preview": True},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram не принял сообщение")


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def analyze(symbol):
    response = requests.get(
        f"{BASE_URL}/openApi/swap/v3/quote/klines",
        params={"symbol": symbol, "interval": "15m", "limit": 100},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != 0:
        print(f"{symbol}: данные недоступны")
        return None

    candles = sorted(data.get("data", []), key=lambda c: int(c["time"]))
    candles = candles[:-1]  # Не анализируем формирующуюся свечу.

    if len(candles) < 60:
        print(f"{symbol}: недостаточно свечей")
        return None

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]

    ema20 = ema(closes[-60:], 20)
    ema50 = ema(closes[-60:], 50)

    changes = [
        closes[i] - closes[i - 1]
        for i in range(len(closes) - 14, len(closes))
    ]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14

    if avg_loss == 0:
        rsi = 100 if avg_gain > 0 else 50
    else:
        rsi = 100 - 100 / (1 + avg_gain / avg_loss)

    true_ranges = []
    for i in range(len(candles) - 14, len(candles)):
        previous_close = closes[i - 1]
        true_ranges.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - previous_close),
                abs(lows[i] - previous_close),
            )
        )

    atr = sum(true_ranges) / len(true_ranges)
    price = closes[-1]

    if ema20 > ema50 and 50 < rsi < 70:
        direction = "LONG"
    elif ema20 < ema50 and 30 < rsi < 50:
        direction = "SHORT"
    else:
        direction = None

    print(
        f"{symbol}: цена={price:.6g}, EMA20={ema20:.6g}, "
        f"EMA50={ema50:.6g}, RSI={rsi:.1f}, "
        f"направление={direction or 'нет сигнала'}"
    )

    if not direction:
        return None

    if direction == "LONG":
        stop_loss = price - 1.5 * atr
        take_profit = price + 3.0 * atr
    else:
        stop_loss = price + 1.5 * atr
        take_profit = price - 3.0 * atr

    return (
        f"📊 Предварительный сигнал {direction}\n"
        f"Пара: {symbol}\n"
        f"Таймфрейм: 15m\n"
        f"Цена закрытия: {price:.6g}\n"
        f"EMA20: {ema20:.6g}\n"
        f"EMA50: {ema50:.6g}\n"
        f"RSI: {rsi:.1f}\n"
        f"ATR (14): {atr:.6g}\n"
        f"Stop-Loss: {stop_loss:.6g}\n"
        f"Take-Profit: {take_profit:.6g}\n\n"
        "⚠️ Учебный сигнал. Это не биржевые ордера и не гарантия результата."
    )


def load_seen_news():
    try:
        with open(SEEN_NEWS_PATH, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()


def save_seen_news(seen):
    # Keep only the latest 1000 IDs so the file does not grow indefinitely.
    items = list(seen)[-1000:]
    with open(SEEN_NEWS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(items))


def get_text(element, tag):
    child = element.find(tag)
    if child is None:
        # Support Atom feeds with namespaces.
        child = element.find("{http://www.w3.org/2005/Atom}" + tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def parse_feed(source, url):
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "CryptoMarketClubNewsBot/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as error:
        print(f"Новости ({source}): не удалось загрузить ленту — {error}")
        return []

    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    articles = []
    for item in items[:20]:
        title = get_text(item, "title")
        description = get_text(item, "description")
        if not description:
            description = get_text(item, "summary")
        link = get_text(item, "link")
        if not link:
            link_element = item.find("{http://www.w3.org/2005/Atom}link")
            if link_element is not None:
                link = link_element.attrib.get("href", "")
        pub_date = get_text(item, "pubDate") or get_text(item, "published")
        guid = get_text(item, "guid") or get_text(item, "id") or link or title
        if not title:
            continue
        articles.append({
            "source": source,
            "title": title,
            "description": description,
            "link": link,
            "date": pub_date,
            "id": hashlib.sha256((source + "|" + guid).encode("utf-8")).hexdigest(),
        })
    return articles


def classify_news(article):
    text = (article["title"] + " " + article["description"]).lower()
    matched_impact = [term for term in HIGH_IMPACT_TERMS if term in text]
    if not matched_impact:
        return None

    positive = sum(1 for term in POSITIVE_TERMS if term in text)
    negative = sum(1 for term in NEGATIVE_TERMS if term in text)

    if positive > negative:
        sentiment = "Предварительно позитивная"
        effect = "Возможная поддержка цены"
    elif negative > positive:
        sentiment = "Предварительно негативная"
        effect = "Возможное давление на цену"
    else:
        sentiment = "Неоднозначная / требует проверки"
        effect = "Направление реакции неясно"

    text_upper = text
    affected = []
    for ticker, terms in COIN_TERMS.items():
        if any(term in text_upper for term in terms):
            affected.append(ticker)
    if not affected:
        affected = ["BTC", "ETH", "рынок в целом"]

    # Headline-based urgency estimate, not a verified measure of market impact.
    if len(matched_impact) >= 2 or any(
        term in text for term in ["hack", "hacked", "exploit", "fed", "interest rate", "etf", "ban"]
    ):
        impact = "ВЫСОКАЯ (предварительно)"
    else:
        impact = "СРЕДНЯЯ (предварительно)"

    return {
        "sentiment": sentiment,
        "effect": effect,
        "affected": affected,
        "impact": impact,
    }


def scan_news(seen):
    print("Проверяем новостные ленты...")
    new_count = 0

    for source, url in NEWS_FEEDS:
        for article in parse_feed(source, url):
            if article["id"] in seen:
                continue

            # Mark every fetched item as seen, including non-impact items,
            # to avoid repeatedly reconsidering old headlines on each scan.
            seen.add(article["id"])
            analysis = classify_news(article)
            if not analysis:
                continue

            description = article["description"].replace("\n", " ").strip()
            if len(description) > 350:
                description = description[:347] + "..."
            date_text = article["date"] or "Время публикации не указано"
            message = (
                f"📰 НОВОСТЬ, ВОЗМОЖНО ВЛИЯЮЩАЯ НА КРИПТОРЫНОК\n\n"
                f"Источник: {article['source']}\n"
                f"Заголовок: {article['title']}\n"
                f"Время: {date_text}\n"
                f"Предварительная важность: {analysis['impact']}\n"
                f"Тональность по ключевым словам: {analysis['sentiment']}\n"
                f"Возможный эффект: {analysis['effect']}\n"
                f"Активы/рынок: {', '.join(analysis['affected'])}\n"
            )
            if description:
                message += f"\nКратко: {description}\n"
            if article["link"]:
                message += f"\nИсточник: {article['link']}"
            message += (
                "\n\n⚠️ Автоматическая оценка только по заголовку/краткому описанию. "
                "Проверь первоисточник: реакция цены может отличаться."
            )

            try:
                send_telegram(message[:4000])
                new_count += 1
                print(f"Новость отправлена: {article['title']}")
            except Exception as error:
                print(f"Ошибка отправки новости в Telegram: {error}")

    save_seen_news(seen)
    print(f"Новостной скан завершён. Отправлено важных новостей: {new_count}")


def scan_market():
    print("Загружаем список контрактов BingX...")
    response = requests.get(
        f"{BASE_URL}/openApi/swap/v2/quote/contracts",
        timeout=20,
    )
    response.raise_for_status()
    result = response.json()

    if result.get("code") != 0:
        print("Не удалось получить контракты:", result)
        return

    contracts = result.get("data", [])
    symbols = []
    for item in contracts:
        symbol = item.get("symbol", "")
        if (
            symbol.endswith("-USDT")
            and symbol.count("-") == 1
            and symbol[:-5].isalnum()
            and item.get("status") in (1, "1", "TRADING", None)
        ):
            symbols.append(symbol)

    preferred = [
        "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT",
        "XRP-USDT", "DOGE-USDT", "ADA-USDT", "LINK-USDT",
        "AVAX-USDT", "LTC-USDT", "PUMP-USDT",
    ]
    selected = [symbol for symbol in preferred if symbol in symbols]
    if len(selected) < 10:
        for symbol in symbols:
            if symbol not in selected:
                selected.append(symbol)
            if len(selected) >= 10:
                break

    print(f"Проверяем {len(selected)} пар...")
    signals = []
    for symbol in selected:
        try:
            signal = analyze(symbol)
            if signal:
                signals.append(signal)
        except Exception as error:
            print(f"{symbol}: ошибка анализа — {error}")
        time.sleep(0.3)

    if signals:
        for signal in signals:
            try:
                send_telegram(signal)
                print("Сигнал отправлен в Telegram.")
            except Exception as error:
                print("Ошибка отправки Telegram:", error)
    else:
        print("Подходящих технических сигналов сейчас нет.")


def main():
    seen = load_seen_news()
    print("CryptoMarketClub запущен. Сканирование каждые 15 минут.")
    print("Нажми Ctrl+C в этом окне, чтобы остановить бота.")

    while True:
        started = time.time()
        print("\n" + "=" * 50)
        print("Начало цикла:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        try:
            scan_market()
        except Exception as error:
            print("Ошибка сканера рынка:", error)

        try:
            scan_news(seen)
        except Exception as error:
            print("Ошибка сканера новостей:", error)

        elapsed = time.time() - started
        wait_seconds = max(10, SCAN_INTERVAL_SECONDS - int(elapsed))
        print(f"Следующая проверка примерно через {wait_seconds // 60} мин.")
        time.sleep(wait_seconds)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем.")
    except Exception as error:
        print("Критическая ошибка программы:", error)

