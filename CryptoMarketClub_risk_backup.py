from pathlib import Path
import requests
import time
import os
import hashlib
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

BASE_URL = "https://open-api.bingx.com"
CHAT_ID = "-1004357087660"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
SEEN_NEWS_PATH = os.path.join(SCRIPT_DIR, "seen_news.txt")
# Schedule: scalp every minute, medium-term every 15 minutes, long-term hourly.
SCALP_INTERVAL_SECONDS = 180
MEDIUM_INTERVAL_SECONDS = 15 * 60
LONG_INTERVAL_SECONDS = 60 * 60
NEWS_INTERVAL_SECONDS = 15 * 60
SENT_SIGNALS_PATH = os.path.join(SCRIPT_DIR, "sent_signals.json")

# Risk management settings
RISK_BALANCE_USDT = 100.0
RISK_PER_TRADE_PCT = 1.0
MAX_DAILY_LOSS_PCT = 3.0
ESTIMATED_ROUND_TRIP_FEE_PCT = 0.10


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
    raise ValueError("ÄËÄÄľÄĹźÄÂµÄËť ÄËťÄÂµ ÄËťÄÂ°ÄÄ…ÄÂ´ÄÂµÄËť ÄË› .env")


def send_telegram(message, thread_id=None):
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


def ema(values, period):
    alpha = 2 / (period + 1)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1 - alpha) * result
    return result


def ema_series(values, period):
    alpha = 2 / (period + 1)
    result = []
    current = values[0]
    for value in values:
        current = alpha * value + (1 - alpha) * current
        result.append(current)
    return result


from smc_module import analyze_smc



def calculate_risk(entry, stop_loss, take_profit, direction):
    """Estimate position sizing and risk; does not place trades."""
    entry = float(entry)
    stop_loss = float(stop_loss)
    take_profit = float(take_profit)

    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        return None

    if direction == "LONG":
        if not stop_loss < entry < take_profit:
            return None
    elif direction == "SHORT":
        if not take_profit < entry < stop_loss:
            return None
    else:
        return None

    risk_usdt = RISK_BALANCE_USDT * RISK_PER_TRADE_PCT / 100.0
    stop_distance_pct = abs(entry - stop_loss) / entry
    if stop_distance_pct <= 0:
        return None

    position_notional = risk_usdt / stop_distance_pct
    fee_rate = ESTIMATED_ROUND_TRIP_FEE_PCT / 100.0
    estimated_fees = position_notional * fee_rate
    reward_distance_pct = abs(take_profit - entry) / entry
    gross_reward = position_notional * reward_distance_pct
    net_reward = gross_reward - estimated_fees

    return {
        "risk_usdt": risk_usdt,
        "position_notional": position_notional,
        "estimated_fees": estimated_fees,
        "gross_reward": gross_reward,
        "net_reward": net_reward,
        "stop_distance_pct": stop_distance_pct * 100.0,
    }


def analyze(symbol, timeframe, mode_name):
    """Create an educational technical signal from the last closed candle."""
    response = requests.get(
        f"{BASE_URL}/openApi/swap/v3/quote/klines",
        params={"symbol": symbol, "interval": timeframe, "limit": 120},
        timeout=20,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != 0:
        print(f"{symbol} {timeframe}: ÄÂ´ÄÂ°ÄËťÄËťĹâ€ąÄÂµ ÄËťÄÂµÄÂ´ÄÄľĹÂĹâ€šĹÂÄĹĽÄËťĹâ€ą")
        return None

    candles = sorted(data.get("data", []), key=lambda c: int(c["time"]))
    if len(candles) > 1:
         candles = candles[:-1]  # ÄĹĄÄÂµ ÄÂ°ÄËťÄÂ°ÄÂ»ÄÂ¸ÄÂ·ÄÂ¸Ĺâ‚¬ĹÂÄÂµÄÄ˝ Ĺâ€žÄÄľĹâ‚¬ÄÄ˝ÄÂ¸Ĺâ‚¬ĹÂĹĹ˝Ĺâ€°ĹÂĹĹ˝ĹÂĹĹą ĹÂÄË›ÄÂµĹâ€ˇĹÂ.
    if len(candles) < 60:
        print(f"{symbol} {timeframe}: ÄËťÄÂµÄÂ´ÄÄľĹÂĹâ€šÄÂ°Ĺâ€šÄÄľĹâ€ˇÄËťÄÄľ ĹÂÄË›ÄÂµĹâ€ˇÄÂµÄÄ…")
        return None

    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    ema20 = ema(closes[-60:], 20)
    ema50 = ema(closes[-60:], 50)

    ema12 = ema_series(closes, 12)
    ema26 = ema_series(closes, 26)
    macd_values = [a - b for a, b in zip(ema12, ema26)]
    macd_signal_values = ema_series(macd_values, 9)
    macd_value = macd_values[-1]
    macd_signal = macd_signal_values[-1]
    macd_hist = macd_value - macd_signal

    bb = closes[-20:]
    bb_mid = sum(bb) / 20
    bb_std = (sum((x - bb_mid) ** 2 for x in bb) / 20) ** 0.5
    bb_upper = bb_mid + 2 * bb_std
    bb_lower = bb_mid - 2 * bb_std

    volume_key = "volume" if "volume" in candles[-1] else "vol"
    volumes = [float(c.get(volume_key, 0) or 0) for c in candles]
    avg_volume = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_volume if avg_volume > 0 else 0


    changes = [closes[i] - closes[i - 1] for i in range(len(closes) - 14, len(closes))]
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
        true_ranges.append(max(highs[i] - lows[i], abs(highs[i] - previous_close), abs(lows[i] - previous_close)))
    atr = sum(true_ranges) / len(true_ranges)
    smc = analyze_smc(candles)
    print("SMC | {} {}: direction={}, BOS={}, sweep={}, FVG={}".format(
        symbol, timeframe, smc["direction"], smc["bos"],
        smc["liquidity_sweep"], smc["fvg"]
    ))
    price = closes[-1]
    candle_time = str(candles[-1].get("time", "unknown"))

    # 3 ÄĹĽÄÄľÄÂ´Ĺâ€šÄË›ÄÂµĹâ‚¬ÄÂ¶ÄÂ´ÄÂµÄËťÄÂ¸ĹĹą: Ĺâ€šĹâ‚¬ÄÂµÄËťÄÂ´, RSI ÄÂ¸ ÄÂ´ÄË›ÄÂ¸ÄÂ¶ÄÂµÄËťÄÂ¸ÄÂµ ÄĹĽÄÄľĹÂÄÂ»ÄÂµÄÂ´ÄËťÄÂ¸Ĺâ€¦ ÄÂ·ÄÂ°ÄĹźĹâ‚¬Ĺâ€ąĹâ€šĹâ€ąĹâ€¦ ĹÂÄË›ÄÂµĹâ€ˇÄÂµÄÄ…
    bullish_trend = ema20 > ema50
    bearish_trend = ema20 < ema50

    bullish_rsi = 50 < rsi < 65
    bearish_rsi = 35 < rsi < 50

    bullish_candles = closes[-1] > closes[-2] > closes[-3]
    bearish_candles = closes[-1] < closes[-2] < closes[-3]

    
    if bullish_trend and bullish_rsi and bullish_candles and macd_hist > 0:
        direction = "LONG"
        rationale = "EMA trend, RSI, candles and positive MACD histogram confirmed"
    elif bearish_trend and bearish_rsi and bearish_candles and macd_hist < 0:
        direction = "SHORT"
        rationale = "EMA trend, RSI, candles and negative MACD histogram confirmed"
    else:
        direction = None
        rationale = "Technical conditions or MACD confirmation not met"

    # Require SMC direction to agree with the technical signal.
    if direction == "LONG" and smc["direction"] != "BULLISH":
        print(f"SMC filter rejected LONG | {symbol} {timeframe}")
        direction = None
    elif direction == "SHORT" and smc["direction"] != "BEARISH":
        print(f"SMC filter rejected SHORT | {symbol} {timeframe}")
        direction = None

    print(f"{mode_name} | {symbol} {timeframe}: price={price:.6g}, EMA20={ema20:.6g}, EMA50={ema50:.6g}, RSI={rsi:.1f}, MACD_hist={macd_hist:.6g}, BB=({bb_lower:.6g}-{bb_upper:.6g}), Volume_ratio={volume_ratio:.2f}")
    if not direction or atr <= 0:
        return None

    # Indicative ATR levels only; no exchange orders are placed.
    sl_mult, tp_mult = (1.2, 1.8) if mode_name == "SCALPING" else ((1.5, 2.5) if mode_name == "MEDIUM-TERM" else (2.0, 3.5))
    if direction == "LONG":
        stop_loss, take_profit = price - sl_mult * atr, price + tp_mult * atr
    else:
        stop_loss, take_profit = price + sl_mult * atr, price - tp_mult * atr

    signal_id = f"{symbol}|{timeframe}|{candle_time}|{direction}"
    message = (
        f"Ä‘Ĺşâ€śĹ  {mode_name}: ÄĹşÄÂ Äâ€˘Äâ€ťÄâ€™ÄÂÄÂ ÄÂÄËÄâ€˘Äâ€şÄÂ¬ÄĹĄÄÂ«Äâ„˘ ÄË‡ÄÂÄâ€śÄĹĄÄÂÄâ€ş {direction}\n\n"
        f"ÄĹşÄÂ°Ĺâ‚¬ÄÂ°: {symbol}\nÄËÄÂ°ÄÄ…ÄÄ˝Ĺâ€žĹâ‚¬ÄÂµÄÄ…ÄÄ˝: {timeframe}\n"
        f"ÄÂ¦ÄÂµÄËťÄÂ° ÄÂ·ÄÂ°ÄĹźĹâ‚¬Ĺâ€ąĹâ€šÄÂ¸ĹĹą: {price:.8g}\nStop-Loss (ÄÄľĹâ‚¬ÄÂ¸ÄÂµÄËťĹâ€šÄÂ¸Ĺâ‚¬): {stop_loss:.8g}\n"
        f"Take-Profit (ÄÄľĹâ‚¬ÄÂ¸ÄÂµÄËťĹâ€šÄÂ¸Ĺâ‚¬): {take_profit:.8g}\n"
        f"EMA20: {ema20:.8g}\nEMA50: {ema50:.8g}\nRSI: {rsi:.1f}\nATR(14): {atr:.8g}\n"
        f"MACD: {macd_value:.8g} | Signal: {macd_signal:.8g} | Histogram: {macd_hist:.8g}\n"
        f"Bollinger Bands (20,2): lower={bb_lower:.8g}, middle={bb_mid:.8g}, upper={bb_upper:.8g}\n"
        f"Volume / 20-candle average: {volume_ratio:.2f}x\n"
        f"ÄĹľÄÂ±ÄÄľĹÂÄËťÄÄľÄË›ÄÂ°ÄËťÄÂ¸ÄÂµ: {rationale}\n\n"
        "Ă˘ĹˇÂ ÄŹÂ¸Ĺą ÄËÄÄľÄÂ»ĹĹšÄĹźÄÄľ ÄÂ°ÄËťÄÂ°ÄÂ»ÄÂ¸Ĺâ€šÄÂ¸Ĺâ€ˇÄÂµĹÂÄĹźÄÂ¸ÄÄ… ĹÂÄÂ¸ÄĹ‚ÄËťÄÂ°ÄÂ», ÄËťÄÂµ Ĺâ€žÄÂ¸ÄËťÄÂ°ÄËťĹÂÄÄľÄË›ÄÂ°ĹĹą Ĺâ‚¬ÄÂµÄĹźÄÄľÄÄ˝ÄÂµÄËťÄÂ´ÄÂ°Ĺâ€ ÄÂ¸ĹĹą. SL/TP Ă˘â‚¬â€ť Ĺâ‚¬ÄÂ°ĹÂĹâ€ˇĹâ€Ĺâ€šÄËťĹâ€ąÄÂµ ĹÂĹâ‚¬ÄÄľÄË›ÄËťÄÂ¸, ÄËťÄÂµ ÄÂ±ÄÂ¸Ĺâ‚¬ÄÂ¶ÄÂµÄË›Ĺâ€ąÄÂµ ÄÄľĹâ‚¬ÄÂ´ÄÂµĹâ‚¬ÄÂ°. ÄĹĹâ€ˇÄÂ¸Ĺâ€šĹâ€ąÄË›ÄÂ°ÄÄ… ÄĹźÄÄľÄÄ˝ÄÂ¸ĹÂĹÂÄÂ¸ĹĹ˝, ÄĹĽĹâ‚¬ÄÄľĹÂÄĹźÄÂ°ÄÂ»ĹĹšÄÂ·Ĺâ€ąÄË›ÄÂ°ÄËťÄÂ¸ÄÂµ ÄÂ¸ Ĺâ‚¬ÄÂ¸ĹÂÄĹź ÄĹĽÄÄľĹâ€šÄÂµĹâ‚¬ÄÂ¸ ĹÂĹâ‚¬ÄÂµÄÂ´ĹÂĹâ€šÄË›."
    )
    return {"id": signal_id, "message": message, "symbol": symbol, "timeframe": timeframe, "candles": candles, "ema20": ema20, "ema50": ema50, "entry": price, "stop_loss": stop_loss, "take_profit": take_profit, "direction": direction}


def load_sent_signals():
    try:
        import json
        with open(SENT_SIGNALS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data if isinstance(data, list) else [])
    except (FileNotFoundError, ValueError, OSError):
        return set()


def save_sent_signals(sent):
    import json
    # Bound the file size; the most recently inserted IDs are kept.
    with open(SENT_SIGNALS_PATH, "w", encoding="utf-8") as f:
        json.dump(list(sent)[-5000:], f, ensure_ascii=False, indent=2)


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
        print(f"ÄĹĄÄÄľÄË›ÄÄľĹÂĹâ€šÄÂ¸ ({source}): ÄËťÄÂµ ĹÂÄÂ´ÄÂ°ÄÂ»ÄÄľĹÂĹĹš ÄÂ·ÄÂ°ÄĹ‚Ĺâ‚¬ĹÂÄÂ·ÄÂ¸Ĺâ€šĹĹš ÄÂ»ÄÂµÄËťĹâ€šĹÂ Ă˘â‚¬â€ť {error}")
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
        sentiment = "ĐźŃ€ĐµĐ´Đ˛Đ°Ń€Đ¸Ń‚ĐµĐ»ŃŚĐ˝Đľ ĐżĐľĐ·Đ¸Ń‚Đ¸Đ˛Đ˝Đ°ŃŹ"
        effect = "Đ’ĐľĐ·ĐĽĐľĐ¶Đ˝Đ°ŃŹ ĐżĐľĐ´Đ´ĐµŃ€Đ¶ĐşĐ° Ń†ĐµĐ˝Ń‹"
    elif negative > positive:
        sentiment = "ĐźŃ€ĐµĐ´Đ˛Đ°Ń€Đ¸Ń‚ĐµĐ»ŃŚĐ˝Đľ Đ˝ĐµĐłĐ°Ń‚Đ¸Đ˛Đ˝Đ°ŃŹ"
        effect = "Đ’ĐľĐ·ĐĽĐľĐ¶Đ˝ĐľĐµ Đ´Đ°Đ˛Đ»ĐµĐ˝Đ¸Đµ Đ˝Đ° Ń†ĐµĐ˝Ń"
    else:
        sentiment = "ĐťĐµĐľĐ´Đ˝ĐľĐ·Đ˝Đ°Ń‡Đ˝Đ°ŃŹ / Ń‚Ń€ĐµĐ±ŃĐµŃ‚ ĐżŃ€ĐľĐ˛ĐµŃ€ĐşĐ¸"
        effect = "ĐťĐ°ĐżŃ€Đ°Đ˛Đ»ĐµĐ˝Đ¸Đµ Ń€ĐµĐ°ĐşŃ†Đ¸Đ¸ Đ˝ĐµŃŹŃĐ˝Đľ"

    text_upper = text
    affected = []
    for ticker, terms in COIN_TERMS.items():
        if any(term in text_upper for term in terms):
            affected.append(ticker)
    if not affected:
        affected = ["BTC", "ETH", "Ń€Ń‹Đ˝ĐľĐş Đ˛ Ń†ĐµĐ»ĐľĐĽ"]

    # Headline-based urgency estimate, not a verified measure of market impact.
    if len(matched_impact) >= 2 or any(
        term in text for term in ["hack", "hacked", "exploit", "fed", "interest rate", "etf", "ban"]
    ):
        impact = "Đ’Đ«ĐˇĐžĐšĐĐŻ (ĐżŃ€ĐµĐ´Đ˛Đ°Ń€Đ¸Ń‚ĐµĐ»ŃŚĐ˝Đľ)"
    else:
        impact = "ĐˇĐ Đ•Đ”ĐťĐŻĐŻ (ĐżŃ€ĐµĐ´Đ˛Đ°Ń€Đ¸Ń‚ĐµĐ»ŃŚĐ˝Đľ)"

    return {
        "sentiment": sentiment,
        "effect": effect,
        "affected": affected,
        "impact": impact,
    }


def scan_news(seen):
    print("ĐźŃ€ĐľĐ˛ĐµŃ€ŃŹĐµĐĽ Đ˝ĐľĐ˛ĐľŃŃ‚Đ˝Ń‹Đµ Đ»ĐµĐ˝Ń‚Ń‹...")
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
            date_text = article["date"] or "Đ’Ń€ĐµĐĽŃŹ ĐżŃĐ±Đ»Đ¸ĐşĐ°Ń†Đ¸Đ¸ Đ˝Đµ ŃĐşĐ°Đ·Đ°Đ˝Đľ"
            message = (
                f"đź“° ĐťĐžĐ’ĐžĐˇĐ˘Đ¬, Đ’ĐžĐ—ĐśĐžĐ–ĐťĐž Đ’Đ›ĐĐŻĐ®Đ©ĐĐŻ ĐťĐ ĐšĐ ĐĐźĐ˘ĐžĐ Đ«ĐťĐžĐš\n\n"
                f"ĐŃŃ‚ĐľŃ‡Đ˝Đ¸Đş: {article['source']}\n"
                f"Đ—Đ°ĐłĐľĐ»ĐľĐ˛ĐľĐş: {article['title']}\n"
                f"Đ’Ń€ĐµĐĽŃŹ: {date_text}\n"
                f"ĐźŃ€ĐµĐ´Đ˛Đ°Ń€Đ¸Ń‚ĐµĐ»ŃŚĐ˝Đ°ŃŹ Đ˛Đ°Đ¶Đ˝ĐľŃŃ‚ŃŚ: {analysis['impact']}\n"
                f"Đ˘ĐľĐ˝Đ°Đ»ŃŚĐ˝ĐľŃŃ‚ŃŚ ĐżĐľ ĐşĐ»ŃŽŃ‡ĐµĐ˛Ń‹ĐĽ ŃĐ»ĐľĐ˛Đ°ĐĽ: {analysis['sentiment']}\n"
                f"Đ’ĐľĐ·ĐĽĐľĐ¶Đ˝Ń‹Đą ŃŤŃ„Ń„ĐµĐşŃ‚: {analysis['effect']}\n"
                f"ĐĐşŃ‚Đ¸Đ˛Ń‹/Ń€Ń‹Đ˝ĐľĐş: {', '.join(analysis['affected'])}\n"
            )
            if description:
                message += f"\nĐšŃ€Đ°Ń‚ĐşĐľ: {description}\n"
            if article["link"]:
                message += f"\nĐŃŃ‚ĐľŃ‡Đ˝Đ¸Đş: {article['link']}"
            message += (
                "\n\nâš ď¸Ź ĐĐ˛Ń‚ĐľĐĽĐ°Ń‚Đ¸Ń‡ĐµŃĐşĐ°ŃŹ ĐľŃ†ĐµĐ˝ĐşĐ° Ń‚ĐľĐ»ŃŚĐşĐľ ĐżĐľ Đ·Đ°ĐłĐľĐ»ĐľĐ˛ĐşŃ/ĐşŃ€Đ°Ń‚ĐşĐľĐĽŃ ĐľĐżĐ¸ŃĐ°Đ˝Đ¸ŃŽ. "
                "ĐźŃ€ĐľĐ˛ĐµŃ€ŃŚ ĐżĐµŃ€Đ˛ĐľĐ¸ŃŃ‚ĐľŃ‡Đ˝Đ¸Đş: Ń€ĐµĐ°ĐşŃ†Đ¸ŃŹ Ń†ĐµĐ˝Ń‹ ĐĽĐľĐ¶ĐµŃ‚ ĐľŃ‚Đ»Đ¸Ń‡Đ°Ń‚ŃŚŃŃŹ."
            )

            try:
                send_telegram(message[:4000], thread_id=13)
                new_count += 1
                print(f"ĐťĐľĐ˛ĐľŃŃ‚ŃŚ ĐľŃ‚ĐżŃ€Đ°Đ˛Đ»ĐµĐ˝Đ°: {article['title']}")
            except Exception as error:
                print(f"ĐžŃĐ¸Đ±ĐşĐ° ĐľŃ‚ĐżŃ€Đ°Đ˛ĐşĐ¸ Đ˝ĐľĐ˛ĐľŃŃ‚Đ¸ Đ˛ Telegram: {error}")

    save_seen_news(seen)
    print(f"ĐťĐľĐ˛ĐľŃŃ‚Đ˝ĐľĐą ŃĐşĐ°Đ˝ Đ·Đ°Đ˛ĐµŃ€ŃŃ‘Đ˝. ĐžŃ‚ĐżŃ€Đ°Đ˛Đ»ĐµĐ˝Đľ Đ˛Đ°Đ¶Đ˝Ń‹Ń… Đ˝ĐľĐ˛ĐľŃŃ‚ĐµĐą: {new_count}")


def get_available_symbols():
    """Select liquid BingX USDT crypto contracts using ticker volume and spread."""
    print("Loading BingX contracts and tickers...")

    contracts_response = requests.get(
        f"{BASE_URL}/openApi/swap/v2/quote/contracts", timeout=20
    )
    contracts_response.raise_for_status()
    contracts_result = contracts_response.json()

    tickers_response = requests.get(
        f"{BASE_URL}/openApi/swap/v2/quote/ticker", timeout=20
    )
    tickers_response.raise_for_status()
    tickers_result = tickers_response.json()

    if contracts_result.get("code") != 0:
        raise RuntimeError("Failed to load BingX contracts")
    if tickers_result.get("code") != 0:
        raise RuntimeError("Failed to load BingX tickers")

    contracts = {
        item.get("symbol"): item
        for item in contracts_result.get("data", [])
        if item.get("symbol")
    }

    # Requested coins are prioritized when available and liquid enough.
    priority = [
        "BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT", "XRP-USDT",
        "DOGE-USDT", "ADA-USDT", "LINK-USDT", "AVAX-USDT", "LTC-USDT",
        "DOT-USDT", "TRX-USDT", "BCH-USDT", "UNI-USDT", "APT-USDT",
        "ARB-USDT", "OP-USDT", "NEAR-USDT", "SUI-USDT", "FIL-USDT",
        "ZEC-USDT",
    ]

    # Exclude known commodity and traditional-market symbols.
    excluded_terms = (
        "GOLD", "OIL", "SILVER", "XAG", "XAU", "WTI", "BRENT",
        "EURUSD", "GBPUSD", "USDJPY", "SP500", "NASDAQ",
    )

    ranked = []
    for ticker in tickers_result.get("data", []):
        symbol = ticker.get("symbol", "")
        contract = contracts.get(symbol)

        if not contract or not symbol.endswith("-USDT"):
            continue
        if symbol.count("-") != 1 or not symbol[:-5].isalnum():
            continue
        if any(term in symbol.upper() for term in excluded_terms):
            continue
        if contract.get("status") not in (1, "1", "TRADING", None):
            continue
        if contract.get("apiStateOpen") in (False, 0, "0"):
            continue

        try:
            volume = float(ticker.get("quoteVolume") or 0)
            bid = float(ticker.get("bidPrice") or 0)
            ask = float(ticker.get("askPrice") or 0)
            price = float(ticker.get("lastPrice") or 0)
        except (TypeError, ValueError):
            continue

        if volume < 1_000_000 or price <= 0 or bid <= 0 or ask < bid:
            continue

        midpoint = (ask + bid) / 2
        if midpoint <= 0:
            continue

        spread_pct = (ask - bid) / midpoint * 100
        if spread_pct > 0.05:
            continue

        ranked.append((symbol, volume, spread_pct))

    ranked.sort(key=lambda item: item[1], reverse=True)
    by_symbol = {item[0]: item for item in ranked}

    # Keep the 50 most liquid markets and include requested coins that pass
    # the same filters, even if their turnover ranks below the top 50.
    selected = [item[0] for item in ranked[:50]]
    for symbol in priority:
        if symbol in by_symbol and symbol not in selected:
            selected.append(symbol)

    if not selected:
        raise RuntimeError("No USDT crypto contracts passed the liquidity filters.")

    print(f"Eligible markets: {len(ranked)}")
    print(f"Markets selected for analysis: {len(selected)}")
    print("Selected symbols: " + ", ".join(selected))
    print("Filters: quote volume >= 1M USDT, spread <= 0.05%.")
    return selected

def scan_modes(symbols, modes, sent_signals):
    sent_count = 0
    for mode_name, timeframes in modes:
        topic_id = {
            "SCALPING": 3,
            "MEDIUM-TERM": 5,
            "LONG-TERM": 6,
            "DAILY": 6,
        }.get(mode_name)
        print(f"\n--- {mode_name}: {', '.join(timeframes)} ---")
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    signal = analyze(symbol, timeframe, mode_name)
                    if signal and signal["id"] not in sent_signals:
                        chart_path = None
                        try:
                            chart_path = create_signal_chart(
                                signal["symbol"], signal["timeframe"],
                                signal["candles"], signal["ema20"], signal["ema50"],
                                signal["entry"], signal["stop_loss"], signal["take_profit"],
                                signal["direction"]
                            )
                            send_telegram_photo(signal["message"], chart_path, thread_id=topic_id)
                        except Exception as chart_error:
                            print(f"ÄĹľĹÂÄÂ¸ÄÂ±ÄĹźÄÂ° ÄĹ‚Ĺâ‚¬ÄÂ°Ĺâ€žÄÂ¸ÄĹźÄÂ°: {chart_error}. ÄĹľĹâ€šÄĹĽĹâ‚¬ÄÂ°ÄË›ÄÂ»ĹĹąÄÂµÄÄ˝ Ĺâ€šÄÂµÄĹźĹÂĹâ€š.")
                            send_telegram(signal["message"], thread_id=topic_id)
                        finally:
                            if chart_path:
                                import os
                                if os.path.exists(chart_path):
                                    os.remove(chart_path)
                        sent_signals.add(signal["id"])
                        sent_count += 1
                        print(f"Ă„ÂĂ‹â€ˇĂ„ÂĂ‚Â¸Ă„ÂÄąâ€šĂ„ÂĂ‹ĹĄĂ„ÂĂ‚Â°Ă„ÂĂ‚Â» Ă„ÂĂ„ÄľÄąÂĂ˘â‚¬ĹˇĂ„ÂÄąÄ˝ÄąÂĂ˘â€šÂ¬Ă„ÂĂ‚Â°Ă„ÂĂ‹â€şĂ„ÂĂ‚Â»Ă„ÂĂ‚ÂµĂ„ÂĂ‹ĹĄ: {symbol} {timeframe} {mode_name}")
                except Exception as error:
                    print(f"{symbol} {timeframe}: Ă„ÂĂ„ÄľÄąÂĂ‚ÂĂ„ÂĂ‚Â¸Ă„ÂĂ‚Â±Ă„ÂÄąĹşĂ„ÂĂ‚Â° Ă„ÂĂ‚Â°Ă„ÂĂ‹ĹĄĂ„ÂĂ‚Â°Ă„ÂĂ‚Â»Ă„ÂĂ‚Â¸Ă„ÂĂ‚Â·Ă„ÂĂ‚Â° Ä‚ËĂ˘â€šÂ¬Ă˘â‚¬ĹĄ {error}")
                time.sleep(0.2)
    if sent_count == 0:
        print("Ă„ÂÄąÄ„Ă„ÂĂ„ÄľĂ„ÂĂ‹â€şÄąÂĂ˘â‚¬Ä…ÄąÂĂ˘â‚¬Â¦ ÄąÂĂ‚ÂĂ„ÂĂ‚Â¸Ă„ÂÄąâ€šĂ„ÂĂ‹ĹĄĂ„ÂĂ‚Â°Ă„ÂĂ‚Â»Ă„ÂĂ„ÄľĂ„ÂĂ‹â€ş Ă„ÂĂ‹â€ş ÄąÂÄąÂ¤ÄąÂĂ˘â‚¬ĹˇĂ„ÂĂ‚Â¸ÄąÂĂ˘â‚¬Â¦ ÄąÂĂ˘â€šÂ¬Ă„ÂĂ‚ÂµĂ„ÂĂ‚Â¶Ă„ÂĂ‚Â¸Ă„ÂĂ„ËťĂ„ÂĂ‚Â°ÄąÂĂ˘â‚¬Â¦ Ă„ÂĂ‹ĹĄĂ„ÂĂ‚ÂµÄąÂĂ˘â‚¬Ĺˇ.")
    save_sent_signals(sent_signals)


def create_signal_chart(symbol, timeframe, candles, ema20, ema50, entry, stop_loss, take_profit, direction):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import os
    import tempfile

    fig, ax = plt.subplots(figsize=(12, 6))
    closes = [float(c["close"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    opens = [float(c["open"]) for c in candles]
    x = list(range(len(candles)))

    for i in x:
        color = "green" if closes[i] >= opens[i] else "red"
        ax.vlines(i, lows[i], highs[i], color=color, linewidth=1)
        bottom = min(opens[i], closes[i])
        height = max(abs(closes[i] - opens[i]), 0.000001)
        ax.bar(i, height, bottom=bottom, color=color, width=0.6)

    def make_ema(values, period):
        alpha = 2 / (period + 1)
        result = values[0]
        line = []
        for value in values:
            result = alpha * value + (1 - alpha) * result
            line.append(result)
        return line

    ax.plot(x, make_ema(closes, 20), label="EMA20", linewidth=1.5)
    ax.plot(x, make_ema(closes, 50), label="EMA50", linewidth=1.5)
    ax.axhline(float(entry), linestyle="-", label=f"Entry: {entry}")
    ax.axhline(float(stop_loss), linestyle="--", label=f"Stop Loss: {stop_loss}")
    ax.axhline(float(take_profit), linestyle="--", label=f"Take Profit: {take_profit}")
    ax.set_title(f"{symbol} | {timeframe} | {direction}")
    ax.legend(loc="best")
    ax.grid(alpha=0.2)
    fig.tight_layout()

    path = os.path.join(tempfile.gettempdir(), f"signal_{symbol.replace('/', '_')}_{timeframe}.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path

def send_telegram_photo(message, image_path, thread_id=None):
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


def main():
    seen_news = load_seen_news()
    sent_signals = load_sent_signals()
    symbols = get_available_symbols()
    scalp_symbols = symbols[:15]
    now = time.time()
    last_scalp = 0
    last_medium = 0
    last_long = 0
    last_news = 0
    last_heatmap = 0

    print("CryptoMarketClub ÄÂ·ÄÂ°ÄĹĽĹÂĹâ€°ÄÂµÄËť: Ĺâ€šÄÄľÄÂ»ĹĹšÄĹźÄÄľ ĹÂÄÂ¸ÄĹ‚ÄËťÄÂ°ÄÂ»Ĺâ€ą, ÄÂ°ÄË›Ĺâ€šÄÄľÄÄ˝ÄÂ°Ĺâ€šÄÂ¸Ĺâ€ˇÄÂµĹÂÄĹźÄÂ¸ÄÂµ ĹÂÄÂ´ÄÂµÄÂ»ÄĹźÄÂ¸ ÄÄľĹâ€šÄĹźÄÂ»ĹĹ˝Ĺâ€ˇÄÂµÄËťĹâ€ą.")
    print("ÄË‡ÄĹźÄÂ°ÄÂ»ĹĹšÄĹĽÄÂ¸ÄËťÄĹ‚ Ă˘â‚¬â€ť ÄĹźÄÂ°ÄÂ¶ÄÂ´ĹÂĹĹ˝ ÄÄ˝ÄÂ¸ÄËťĹÂĹâ€šĹÂ; ĹÂĹâ‚¬ÄÂµÄÂ´ÄËťÄÂµĹÂĹâ‚¬ÄÄľĹâ€ˇÄËťĹâ€ąÄÄ… Ă˘â‚¬â€ť ÄĹźÄÂ°ÄÂ¶ÄÂ´Ĺâ€ąÄÂµ 15 ÄÄ˝ÄÂ¸ÄËťĹÂĹâ€š; ÄÂ´ÄÄľÄÂ»ÄĹ‚ÄÄľĹÂĹâ‚¬ÄÄľĹâ€ˇÄËťĹâ€ąÄÄ… Ă˘â‚¬â€ť ÄĹźÄÂ°ÄÂ¶ÄÂ´Ĺâ€ąÄÄ… Ĺâ€ˇÄÂ°ĹÂ.")
    print("ÄĹĄÄÄľÄË›ÄÄľĹÂĹâ€šÄÂ¸ Ă˘â‚¬â€ť ÄĹźÄÂ°ÄÂ¶ÄÂ´Ĺâ€ąÄÂµ 15 ÄÄ˝ÄÂ¸ÄËťĹÂĹâ€š. Äâ€ťÄÂ»ĹĹą ÄÄľĹÂĹâ€šÄÂ°ÄËťÄÄľÄË›ÄĹźÄÂ¸ ÄËťÄÂ°ÄÂ¶ÄÄ˝ÄÂ¸ Ctrl+C.")

    while True:
        now = time.time()
        print("\n" + "=" * 55)
        print("ÄĹşĹâ‚¬ÄÄľÄË›ÄÂµĹâ‚¬ÄĹźÄÂ°:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # Refresh the contract list every 6 hours so new/removed markets are handled.
        if not symbols or int(now) % (6 * 60 * 60) < 60:
            try:
                symbols = get_available_symbols()
                scalp_symbols = symbols[:15]
            except Exception as error:
                print("ÄĹĄÄÂµ ĹÂÄÂ´ÄÂ°ÄÂ»ÄÄľĹÂĹĹš ÄÄľÄÂ±ÄËťÄÄľÄË›ÄÂ¸Ĺâ€šĹĹš ĹÂÄĹĽÄÂ¸ĹÂÄÄľÄĹź ÄĹźÄÄľÄËťĹâ€šĹâ‚¬ÄÂ°ÄĹźĹâ€šÄÄľÄË›:", error)

        if now - last_scalp >= SCALP_INTERVAL_SECONDS:
            try:
                scan_modes(scalp_symbols, [("SCALPING", ["1m", "5m"])], sent_signals)
            except Exception as error:
                print("ÄĹľĹÂÄÂ¸ÄÂ±ÄĹźÄÂ° ĹÂÄĹźÄÂ°ÄÂ»ĹĹšÄĹĽÄÂ¸ÄËťÄĹ‚-ĹÂÄĹźÄÂ°ÄËťÄÂµĹâ‚¬ÄÂ°:", error)
            last_scalp = time.time()

        if now - last_medium >= MEDIUM_INTERVAL_SECONDS:
            try:
                scan_modes(symbols, [("MEDIUM-TERM", ["15m"])], sent_signals)
                scan_modes(symbols, [("LONG-TERM", ["1h"])], sent_signals)
            except Exception as error:
                print("ÄĹľĹÂÄÂ¸ÄÂ±ÄĹźÄÂ° ĹÂĹâ‚¬ÄÂµÄÂ´ÄËťÄÂµĹÂĹâ‚¬ÄÄľĹâ€ˇÄËťÄÄľÄĹ‚ÄÄľ ĹÂÄĹźÄÂ°ÄËťÄÂµĹâ‚¬ÄÂ°:", error)
            last_medium = time.time()

        if now - last_long >= LONG_INTERVAL_SECONDS:
            try:
                scan_modes(symbols, [("DAILY", ["1d"])], sent_signals)
            except Exception as error:
                print("ÄĹľĹÂÄÂ¸ÄÂ±ÄĹźÄÂ° ÄÂ´ÄËťÄÂµÄË›ÄËťÄÄľÄĹ‚ÄÄľ ĹÂÄĹźÄÂ°ÄËťÄÂµĹâ‚¬ÄÂ°:", error)
            last_long = time.time()

        if now - last_news >= NEWS_INTERVAL_SECONDS:
            try:
                scan_news(seen_news)
            except Exception as error:
                print("ÄĹľĹÂÄÂ¸ÄÂ±ÄĹźÄÂ° ĹÂÄĹźÄÂ°ÄËťÄÂµĹâ‚¬ÄÂ° ÄËťÄÄľÄË›ÄÄľĹÂĹâ€šÄÂµÄÄ…:", error)
            last_news = time.time()

        if now - last_heatmap >= 15 * 60:
            heatmap_path = None
            try:
                heatmap_path = create_market_heatmap(symbols)
                send_telegram_photo(
                    "CryptoMarketClub | Market Heatmap\n"
                    "Crypto market overview for selected USDT pairs.",
                    heatmap_path,
                    thread_id=4,
                )
                print("Market heatmap sent to Telegram.")
            except Exception as error:
                print("Market heatmap error:", error)
            finally:
                if heatmap_path and os.path.exists(heatmap_path):
                    os.remove(heatmap_path)
            last_heatmap = time.time()

        # A one-second loop keeps the minute schedule responsive without busy-waiting.
        time.sleep(5)







if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nÄâ€ÄÄľĹâ€š ÄÄľĹÂĹâ€šÄÂ°ÄËťÄÄľÄË›ÄÂ»ÄÂµÄËť ÄĹĽÄÄľÄÂ»ĹĹšÄÂ·ÄÄľÄË›ÄÂ°Ĺâ€šÄÂµÄÂ»ÄÂµÄÄ˝.")
    except Exception as error:
        print("ÄĹˇĹâ‚¬ÄÂ¸Ĺâ€šÄÂ¸Ĺâ€ˇÄÂµĹÂÄĹźÄÂ°ĹĹą ÄÄľĹÂÄÂ¸ÄÂ±ÄĹźÄÂ° ÄĹĽĹâ‚¬ÄÄľÄĹ‚Ĺâ‚¬ÄÂ°ÄÄ˝ÄÄ˝Ĺâ€ą:", error)


