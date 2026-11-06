from pathlib import Path
import requests
import time
import os
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

BASE_URL = "https://open-api.bingx.com"
CHAT_ID = "@fgfgfffgff"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
SEEN_NEWS_PATH = os.path.join(SCRIPT_DIR, "seen_news.txt")
# Schedule: scalp every minute, medium-term every 15 minutes, long-term hourly.
SCALP_INTERVAL_SECONDS = 60
MEDIUM_INTERVAL_SECONDS = 15 * 60
LONG_INTERVAL_SECONDS = 60 * 60
DAILY_INTERVAL_SECONDS = 24 * 60 * 60
NEWS_INTERVAL_SECONDS = 15 * 60
SENT_SIGNALS_PATH = os.path.join(SCRIPT_DIR, "sent_signals.json")

# Risk management settings
RISK_BALANCE_USDT = 1000.0
RISK_PER_TRADE_PCT = 10.0
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
    raise ValueError("Ä‚â€žĂ‚ÂÄ‚â€ąĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„ Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€žĂ˘â‚¬Â¦Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„ Ä‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬Ĺź .env")


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

    fee_rate = ESTIMATED_ROUND_TRIP_FEE_PCT / 100.0
    position_notional = risk_usdt / (stop_distance_pct + fee_rate)
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
        print(f"{symbol} {timeframe}: Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂĂ„Ä…Ă„ËťÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦")
        return None

    candles = sorted(data.get("data", []), key=lambda c: int(c["time"]))
    if len(candles) > 1:
         candles = candles[:-1]  # Ä‚â€žĂ‚ÂĂ„Ä…Ă„â€žÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â·Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄ Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąÄľÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂĂ„Ä…Ă‹ĹĄĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‚Â°Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂĂ„Ä…Ă‹ĹĄĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂĂ„Ä…Ă„â€¦ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇĂ„Ä…Ă‚ÂÄ‚â€šĂ‚Â.
    if len(candles) < 60:
        print(f"{symbol} {timeframe}: Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€žĂ„Äľ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€žĂ˘â‚¬Â¦")
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
    print("SMC | {} {}: direction={}, BOS={}, sweep={}, FVG={}, reason={}".format(
        symbol, timeframe, smc["direction"], smc["bos"],
        smc["liquidity_sweep"], smc["fvg"], smc["reason"]
    ))
    price = closes[-1]
    candle_time = str(candles[-1].get("time", "unknown"))

    # 3 Ä‚â€žĂ‚ÂĂ„Ä…Ă„ËťÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¶Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂĂ„Ä…Ă„â€¦: Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´, RSI Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸ Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¶Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ Ä‚â€žĂ‚ÂĂ„Ä…Ă„ËťÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‚Â¦ Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â·Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‚Â¦ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€žĂ˘â‚¬Â¦
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
        print(
            f"SMC filter rejected LONG | {symbol} {timeframe} | "
            f"direction={smc['direction']} | reason={smc['reason']}"
        )
        direction = None
    elif direction == "SHORT" and smc["direction"] != "BEARISH":
        print(
            f"SMC filter rejected SHORT | {symbol} {timeframe} | "
            f"direction={smc['direction']} | reason={smc['reason']}"
        )
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

    risk = calculate_risk(price, stop_loss, take_profit, direction)
    risk_text = ""
    if risk:
        risk_text = (
            "\n\nRISK MANAGEMENT (ESTIMATE)\n"
            f"Balance: {RISK_BALANCE_USDT:.2f} USDT\n"
            f"Risk per trade: {RISK_PER_TRADE_PCT:.2f}% "
            f"({risk['risk_usdt']:.2f} USDT)\n"
            f"Position size: {risk['position_notional']:.2f} USDT "
            "(notional, before leverage)\n"
            f"Distance to SL: {risk['stop_distance_pct']:.2f}%\n"
            f"Estimated fees: {risk['estimated_fees']:.4f} USDT\n"
            f"Potential result after fees: "
            f"{risk['net_reward']:.4f} USDT"
        )

    signal_id = f"{symbol}|{timeframe}|{candle_time}|{direction}"

    risk_reward = None
    if risk and risk["risk_usdt"] > 0:
        risk_reward = risk["net_reward"] / risk["risk_usdt"]

    direction_label = "đźź˘ LONG â€” ĐľĐ¶Đ¸Đ´Đ°Đ˝Đ¸Đµ Ń€ĐľŃŃ‚Đ°" if direction == "LONG" else "đź”´ SHORT â€” ĐľĐ¶Đ¸Đ´Đ°Đ˝Đ¸Đµ ŃĐ˝Đ¸Đ¶ĐµĐ˝Đ¸ŃŹ"

    # Simple structure summary based on recent price movement.
    recent_closes = [float(c["close"]) for c in candles[-10:]]
    if len(recent_closes) >= 6:
        first_half = sum(recent_closes[:len(recent_closes)//2]) / (len(recent_closes)//2)
        second_half = sum(recent_closes[len(recent_closes)//2:]) / (len(recent_closes) - len(recent_closes)//2)
        if second_half > first_half:
            structure_text = "Đ¦ĐµĐ˝Đ° Đ˛ ĐżĐľŃĐ»ĐµĐ´Đ˝Đ¸Ń… ŃĐ˛ĐµŃ‡Đ°Ń… Đ´Đ˛Đ¸Đ¶ĐµŃ‚ŃŃŹ Đ˛Đ˛ĐµŃ€Ń…."
        elif second_half < first_half:
            structure_text = "Đ¦ĐµĐ˝Đ° Đ˛ ĐżĐľŃĐ»ĐµĐ´Đ˝Đ¸Ń… ŃĐ˛ĐµŃ‡Đ°Ń… Đ´Đ˛Đ¸Đ¶ĐµŃ‚ŃŃŹ Đ˛Đ˝Đ¸Đ·."
        else:
            structure_text = "Đ¦ĐµĐ˝Đ° Đ´Đ˛Đ¸Đ¶ĐµŃ‚ŃŃŹ Đ˛ Đ±ĐľĐşĐľĐ˛ĐľĐĽ Đ´Đ¸Đ°ĐżĐ°Đ·ĐľĐ˝Đµ."
    else:
        structure_text = "ĐťĐµĐ´ĐľŃŃ‚Đ°Ń‚ĐľŃ‡Đ˝Đľ ŃĐ˛ĐµŃ‡ĐµĐą Đ´Đ»ŃŹ ĐľŃ†ĐµĐ˝ĐşĐ¸ Đ»ĐľĐşĐ°Đ»ŃŚĐ˝ĐľĐłĐľ Đ´Đ˛Đ¸Đ¶ĐµĐ˝Đ¸ŃŹ."

    rr_text = f"1:{risk_reward:.2f}" if risk_reward is not None else "Đ˝Đµ Ń€Đ°ŃŃŃ‡Đ¸Ń‚Đ°Đ˝Đľ"

    message = (
        f"đź“Š CryptoMarketClub | {mode_name.upper()}\n\n"
        f"{direction_label}\n"
        f"ĐśĐľĐ˝ĐµŃ‚Đ°: {symbol}\n"
        f"Đ˘Đ°ĐąĐĽŃ„Ń€ĐµĐąĐĽ: {timeframe}\n"
        f"Đ¦ĐµĐ˝Đ° Đ˛Ń…ĐľĐ´Đ° (Entry): {price:.8g}\n"
        f"ĐˇŃ‚ĐľĐż-Đ»ĐľŃŃ (SL): {stop_loss:.8g}\n"
        f"Đ˘ĐµĐąĐş-ĐżŃ€ĐľŃ„Đ¸Ń‚ (TP): {take_profit:.8g}\n\n"
        f"âš–ď¸Ź Đ Đ¸ŃĐş/ĐżŃ€Đ¸Đ±Ń‹Đ»ŃŚ: {rr_text}\n"
        f"đź§­ ĐˇŃ‚Ń€ŃĐşŃ‚ŃŃ€Đ° Ń€Ń‹Đ˝ĐşĐ°: {structure_text}\n"
    )

    if risk:
        message += (
            "\nđź›ˇď¸Ź ĐŁĐźĐ ĐĐ’Đ›Đ•ĐťĐĐ• Đ ĐĐˇĐšĐžĐś (ĐľŃ†ĐµĐ˝ĐşĐ°)\n"
            f"Đ‘Đ°Đ»Đ°Đ˝Ń Đ´Đ»ŃŹ Ń€Đ°ŃŃ‡Ń‘Ń‚Đ°: {RISK_BALANCE_USDT:.2f} USDT\n"
            f"Đ Đ¸ŃĐş Đ˝Đ° ŃĐ´ĐµĐ»ĐşŃ: {RISK_PER_TRADE_PCT:.2f}% "
            f"({risk['risk_usdt']:.2f} USDT)\n"
            f"Đ Đ°ŃŃ‡Ń‘Ń‚Đ˝Ń‹Đą Ń€Đ°Đ·ĐĽĐµŃ€ ĐżĐľĐ·Đ¸Ń†Đ¸Đ¸: {risk['position_notional']:.2f} USDT\n"
            f"Đ Đ°ŃŃ‡Ń‘Ń‚Đ˝Ń‹Đµ ĐşĐľĐĽĐ¸ŃŃĐ¸Đ¸: {risk['estimated_fees']:.2f} USDT\n"
            f"ĐźĐľŃ‚ĐµĐ˝Ń†Đ¸Đ°Đ»ŃŚĐ˝Ń‹Đą Ń€ĐµĐ·ŃĐ»ŃŚŃ‚Đ°Ń‚ ĐżĐľŃĐ»Đµ ĐşĐľĐĽĐ¸ŃŃĐ¸Đą: {risk['net_reward']:.2f} USDT\n"
        )

    message += (
        "\nâš ď¸Ź Đ­Ń‚Đľ Đ°Đ˝Đ°Đ»Đ¸Ń‚Đ¸Ń‡ĐµŃĐşĐ¸Đą ŃĐ¸ĐłĐ˝Đ°Đ», Đ° Đ˝Đµ ĐłĐ°Ń€Đ°Đ˝Ń‚Đ¸ŃŹ Ń€ĐµĐ·ŃĐ»ŃŚŃ‚Đ°Ń‚Đ°. "
        "ĐźŃ€ĐľĐ˛ĐµŃ€ŃŚŃ‚Đµ ĐłŃ€Đ°Ń„Đ¸Đş Đ¸ Ń€Đ¸ŃĐş ĐżĐµŃ€ĐµĐ´ ĐżŃ€Đ¸Đ˝ŃŹŃ‚Đ¸ĐµĐĽ Ń€ĐµŃĐµĐ˝Đ¸ŃŹ."
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
        print(f"Ä‚â€žĂ‚ÂĂ„Ä…Ă„â€žÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸ ({source}): Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂĂ„Ä…ÄąË‡ Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â·Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂĂ„Ä…Ă˘â‚¬ĹˇĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â·Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂĂ„Ä…ÄąË‡ Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂÄ‚â€šĂ‚Â Ă„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚ËĂ˘â€šÂ¬ÄąÄ„ {error}")
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
        sentiment = "ĐźĐľĐ·Đ¸Ń‚Đ¸Đ˛Đ˝ĐľĐµ"
        effect = "Đ’ĐľĐ·ĐĽĐľĐ¶Đ˝Đ°ŃŹ ĐżĐľĐ´Đ´ĐµŃ€Đ¶ĐşĐ° Ń†ĐµĐ˝Ń‹"
    elif negative > positive:
        sentiment = "ĐťĐµĐłĐ°Ń‚Đ¸Đ˛Đ˝ĐľĐµ"
        effect = "Đ’ĐľĐ·ĐĽĐľĐ¶Đ˝ĐľĐµ Đ´Đ°Đ˛Đ»ĐµĐ˝Đ¸Đµ Đ˝Đ° Ń†ĐµĐ˝Ń"
    else:
        sentiment = "ĐťĐµĐąŃ‚Ń€Đ°Đ»ŃŚĐ˝ĐľĐµ / ŃĐĽĐµŃĐ°Đ˝Đ˝ĐľĐµ"
        effect = "ĐťĐ°ĐżŃ€Đ°Đ˛Đ»ĐµĐ˝Đ¸Đµ Đ˛Đ»Đ¸ŃŹĐ˝Đ¸ŃŹ Đ˝ĐµŃŹŃĐ˝Đľ"

    affected = []
    for ticker, terms in COIN_TERMS.items():
        if any(term in text for term in terms):
            affected.append(ticker)
    if not affected:
        affected = ["BTC", "ETH", "ĐşŃ€Đ¸ĐżŃ‚ĐľŃ€Ń‹Đ˝ĐľĐş"]

    if len(matched_impact) >= 2 or any(
        term in text for term in [
            "hack", "hacked", "exploit", "fed",
            "interest rate", "etf", "ban"
        ]
    ):
        impact = "Đ’Ń‹ŃĐľĐşĐľĐµ (ĐżŃ€ĐµĐ´Đ˛Đ°Ń€Đ¸Ń‚ĐµĐ»ŃŚĐ˝Đ°ŃŹ ĐľŃ†ĐµĐ˝ĐşĐ°)"
    else:
        impact = "ĐˇŃ€ĐµĐ´Đ˝ĐµĐµ (ĐżŃ€ĐµĐ´Đ˛Đ°Ń€Đ¸Ń‚ĐµĐ»ŃŚĐ˝Đ°ŃŹ ĐľŃ†ĐµĐ˝ĐşĐ°)"

    return {
        "sentiment": sentiment,
        "effect": effect,
        "affected": affected,
        "impact": impact,
    }


def clean_news_text(text):
    text = re.sub(r"<[^>]*>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\\s+", " ", text).strip()


def scan_news(seen):
    print("ĐźŃ€ĐľĐ˛ĐµŃ€ĐşĐ° ĐşŃ€Đ¸ĐżŃ‚ĐľĐ˛Đ°Đ»ŃŽŃ‚Đ˝Ń‹Ń… Đ˝ĐľĐ˛ĐľŃŃ‚ĐµĐą...")
    new_count = 0

    for feed_source, feed_url in NEWS_FEEDS:
        for article in parse_feed(feed_source, feed_url):
            if article["id"] in seen:
                continue

            analysis = classify_news(article)
            if not analysis:
                seen.add(article["id"])
                continue

            description = clean_news_text(article.get("description") or "")
            if len(description) > 350:
                description = description[:347] + "..."

            date_text = article.get("date") or "\u0414\u0430\u0442\u0430 \u043d\u0435 \u0443\u043a\u0430\u0437\u0430\u043d\u0430"
            message = (
                "\U0001F4CA \u041a\u0420\u0418\u041f\u0422\u041e\u041d\u041e\u0412\u041e\u0421\u0422\u0418\n\n"
                f"\U0001F4F0 \u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a: {article['source']}\n"
                f"\U0001F4CC \u0417\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a: {article['title']}\n"
                f"\U0001F4C5 \u0414\u0430\u0442\u0430: {date_text}\n"
                f"\U0001F4A5 \u0412\u043b\u0438\u044f\u043d\u0438\u0435: {analysis['impact']}\n"
                f"\U0001F4C8 \u041d\u0430\u0441\u0442\u0440\u043e\u0435\u043d\u0438\u0435 \u0440\u044b\u043d\u043a\u0430: {analysis['sentiment']}\n"
                f"\U0001F50E \u0412\u043e\u0437\u043c\u043e\u0436\u043d\u044b\u0439 \u044d\u0444\u0444\u0435\u043a\u0442: {analysis['effect']}\n"
                f"\U0001F3AF \u0410\u043a\u0442\u0438\u0432\u044b: {', '.join(analysis['affected'])}\n"
            )

            if description:
                message += f"\n\U0001F4AC \u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435: {description}\n"
            if article.get("link"):
                message += f"\n\U0001F517 \u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a \u0438 \u043f\u043e\u0434\u0440\u043e\u0431\u043d\u043e\u0441\u0442\u0438: {article['link']}"

            message += (
                "\n\n\u26A0\uFE0F \u0418\u043d\u0444\u043e\u0440\u043c\u0430\u0446\u0438\u044f \u0434\u043b\u044f \u043e\u0431\u0443\u0447\u0435\u043d\u0438\u044f, \u0430 \u043d\u0435 \u0444\u0438\u043d\u0430\u043d\u0441\u043e\u0432\u044b\u0439 \u0441\u043e\u0432\u0435\u0442. "
                "\u041f\u0435\u0440\u0435\u0434 \u0442\u043e\u0440\u0433\u043e\u0432\u043b\u0435\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u044f\u0439\u0442\u0435 \u0434\u0430\u043d\u043d\u044b\u0435 \u0438 \u0440\u0438\u0441\u043a\u0438."
            )

            try:
                send_telegram(message[:4000])
                seen.add(article["id"])
                new_count += 1
                print("\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0430 \u043d\u043e\u0432\u043e\u0441\u0442\u044c:", article["title"])
            except Exception as error:
                print("\u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438 \u043d\u043e\u0432\u043e\u0441\u0442\u0438:", error)

        save_seen_news(seen)
    print("ĐźŃ€ĐľĐ˛ĐµŃ€ĐşĐ° Đ˝ĐľĐ˛ĐľŃŃ‚ĐµĐą Đ·Đ°Đ˛ĐµŃ€ŃĐµĐ˝Đ°. ĐžŃ‚ĐżŃ€Đ°Đ˛Đ»ĐµĐ˝Đľ:", new_count)


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
    from daily_risk import daily_status

    status = daily_status()
    if status["limit_reached"]:
        print(
            f"DAILY LOSS LIMIT REACHED: "
            f"{status['daily_pnl_usdt']} USDT. "
            "Skipping new signals."
        )
        return
    sent_count = 0
    for mode_name, timeframes in modes:
        # The destination is a regular Telegram channel, so forum topic IDs
        # from the previous supergroup must not be sent.
        topic_id = None
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
                            print(f"Ä‚â€žĂ‚ÂĂ„Ä…Ă„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â±Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â° Ä‚â€žĂ‚ÂĂ„Ä…Ă˘â‚¬ĹˇĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąÄľÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°: {chart_error}. Ä‚â€žĂ‚ÂĂ„Ä…Ă„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂĂ„Ä…Ă„ËťĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ă„Ä…Ă‚ÂĂ„Ä…Ă„â€¦Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄ Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹźĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡.")
                            send_telegram(signal["message"], thread_id=topic_id)
                        finally:
                            if chart_path:
                                import os
                                if os.path.exists(chart_path):
                                    os.remove(chart_path)
                        sent_signals.add(signal["id"])
                        sent_count += 1
                        print(f"Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ä‚ËĂ˘â€šÂ¬Ă‹â€ˇĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â¸Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂÄ‚â€žĂ„â€¦Ä‚ËĂ˘â€šÂ¬ÄąË‡Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ă„Ä…Ă„â€žĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â°Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â» Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹľÄ‚â€žĂ„ÄľÄ‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă‹â€ˇĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂÄ‚â€žĂ„â€¦Ä‚â€žĂ‹ĹĄÄ‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€šĂ‚Â¬Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â°Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ä‚ËĂ˘â€šÂ¬ÄąĹşĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â»Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚ÂµĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ă„Ä…Ă„â€ž: {symbol} {timeframe} {mode_name}")
                except Exception as error:
                    print(f"{symbol} {timeframe}: Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹľÄ‚â€žĂ„ÄľÄ‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â¸Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â±Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂÄ‚â€žĂ„â€¦Ă„Ä…ÄąĹşĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â° Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â°Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ă„Ä…Ă„â€žĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â°Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â»Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â¸Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â·Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â° Ä‚â€žĂ˘â‚¬ĹˇÄ‚â€ąĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€šĂ‚Â¬Ă„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă„â€ž {error}")
                time.sleep(0.2)
    if sent_count == 0:
        print("Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂÄ‚â€žĂ„â€¦Ä‚â€žĂ˘â‚¬ĹľĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹľÄ‚â€žĂ„ÄľĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ä‚ËĂ˘â€šÂ¬ÄąĹşÄ‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ˘â‚¬Â¦Ä‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€šĂ‚Â¦ Ä‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â¸Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂÄ‚â€žĂ„â€¦Ä‚ËĂ˘â€šÂ¬ÄąË‡Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ă„Ä…Ă„â€žĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â°Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â»Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹľÄ‚â€žĂ„ÄľĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ä‚ËĂ˘â€šÂ¬ÄąĹş Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ä‚ËĂ˘â€šÂ¬ÄąĹş Ä‚â€žĂ„â€¦Ä‚â€šĂ‚ÂÄ‚â€žĂ„â€¦Ä‚â€šĂ‚Â¤Ä‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă‹â€ˇĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â¸Ä‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€šĂ‚Â¦ Ä‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€šĂ‚Â¬Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚ÂµĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â¶Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â¸Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹľÄ‚â€ąÄąÄ„Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚Â°Ä‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€šĂ‚Â¦ Ă„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬Ä…Ă„Ä…Ă„â€žĂ„â€šĂ˘â‚¬ĹľÄ‚â€šĂ‚ÂĂ„â€šĂ˘â‚¬ĹˇÄ‚â€šĂ‚ÂµÄ‚â€žĂ„â€¦Ä‚â€šĂ‚ÂĂ„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ă„Ä…Ă‹â€ˇ.")
    save_sent_signals(sent_signals)


def create_signal_chart(symbol, timeframe, candles, ema20, ema50, entry, stop_loss, take_profit, direction):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import os
    import tempfile

    if len(candles) < 5:
        raise ValueError("ĐťĐµĐ´ĐľŃŃ‚Đ°Ń‚ĐľŃ‡Đ˝Đľ ŃĐ˛ĐµŃ‡ĐµĐą Đ´Đ»ŃŹ ĐżĐľŃŃ‚Ń€ĐľĐµĐ˝Đ¸ŃŹ ĐłŃ€Đ°Ń„Đ¸ĐşĐ°")

    opens = [float(c["open"]) for c in candles]
    highs = [float(c["high"]) for c in candles]
    lows = [float(c["low"]) for c in candles]
    closes = [float(c["close"]) for c in candles]
    x = list(range(len(candles)))

    def make_ema(values, period):
        alpha = 2 / (period + 1)
        result = values[0]
        line = []
        for value in values:
            result = alpha * value + (1 - alpha) * result
            line.append(result)
        return line

    ema20_values = list(ema20) if ema20 is not None else make_ema(closes, 20)
    ema50_values = list(ema50) if ema50 is not None else make_ema(closes, 50)

    # Identify local swing highs and lows.
    swing_highs = []
    swing_lows = []
    for i in range(2, len(candles) - 2):
        if highs[i] >= max(highs[i-2:i+3]):
            swing_highs.append(i)
        if lows[i] <= min(lows[i-2:i+3]):
            swing_lows.append(i)

    # Compare the latest swing points to describe market structure.
    structure = "NEUTRAL"
    explanation = "No clear sequence of higher highs or lower lows"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        higher_highs = highs[swing_highs[-1]] > highs[swing_highs[-2]]
        higher_lows = lows[swing_lows[-1]] > lows[swing_lows[-2]]
        lower_highs = highs[swing_highs[-1]] < highs[swing_highs[-2]]
        lower_lows = lows[swing_lows[-1]] < lows[swing_lows[-2]]

        if higher_highs and higher_lows:
            structure = "UPTREND"
            explanation = "HH + HL: swing highs and lows are rising"
        elif lower_highs and lower_lows:
            structure = "DOWNTREND"
            explanation = "LH + LL: swing highs and lows are falling"
        else:
            explanation = "Mixed swing structure: trend is not confirmed"

    fig, ax = plt.subplots(figsize=(13, 7))
    fig.patch.set_facecolor("#101318")
    ax.set_facecolor("#101318")

    # BingX-inspired candles.
    for i in x:
        color = "#00C087" if closes[i] >= opens[i] else "#F6465D"
        ax.vlines(i, lows[i], highs[i], color=color, linewidth=1.0, zorder=2)
        bottom = min(opens[i], closes[i])
        height = max(abs(closes[i] - opens[i]), max(abs(closes[i]), 1) * 0.00001)
        ax.add_patch(Rectangle(
            (i - 0.32, bottom), 0.64, height,
            facecolor=color, edgecolor=color, linewidth=0.6, zorder=3
        ))

    ax.plot(x, ema20_values, color="#F0B90B", linewidth=1.2, label="EMA 20")
    ax.plot(x, ema50_values, color="#8B7CFF", linewidth=1.2, label="EMA 50")

    # Mark swing structure and connect the latest pivots.
    for j, idx in enumerate(swing_highs):
        label = ""
        if j > 0:
            label = "HH" if highs[idx] > highs[swing_highs[j-1]] else "LH"
        if j == len(swing_highs) - 1 and not label:
            label = "Swing high"
        if label:
            ax.annotate(
                label, (idx, highs[idx]), xytext=(0, 9),
                textcoords="offset points", ha="center",
                color="#F0B90B", fontsize=8, fontweight="bold"
            )

    for j, idx in enumerate(swing_lows):
        label = ""
        if j > 0:
            label = "HL" if lows[idx] > lows[swing_lows[j-1]] else "LL"
        if j == len(swing_lows) - 1 and not label:
            label = "Swing low"
        if label:
            ax.annotate(
                label, (idx, lows[idx]), xytext=(0, -14),
                textcoords="offset points", ha="center",
                color="#5AA9FF", fontsize=8, fontweight="bold"
            )

    # Trendlines through the latest two swing points.
    if len(swing_highs) >= 2:
        a, b = swing_highs[-2], swing_highs[-1]
        ax.plot([a, b], [highs[a], highs[b]], color="#F0B90B",
                linestyle="--", linewidth=1.1, alpha=0.9)
    if len(swing_lows) >= 2:
        a, b = swing_lows[-2], swing_lows[-1]
        ax.plot([a, b], [lows[a], lows[b]], color="#5AA9FF",
                linestyle="--", linewidth=1.1, alpha=0.9)

    # Horizontal trade levels.
    ax.axhline(float(entry), color="#FFFFFF", linestyle="-",
               linewidth=1.0, label=f"Entry: {entry}")
    ax.axhline(float(stop_loss), color="#F6465D", linestyle="--",
               linewidth=1.0, label=f"SL: {stop_loss}")
    ax.axhline(float(take_profit), color="#00C087", linestyle="--",
               linewidth=1.0, label=f"TP: {take_profit}")

    # Display a simple, transparent trend explanation.
    ax.text(
        0.015, 0.97,
        f"STRUCTURE: {structure}\n{explanation}",
        transform=ax.transAxes, va="top", ha="left",
        color="#FFFFFF", fontsize=9,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#202630",
                  edgecolor="#454D5A", alpha=0.95)
    )

    ax.set_title(f"{symbol} | {timeframe} | SIGNAL: {direction}",
                 color="#FFFFFF", fontsize=13, fontweight="bold", pad=14)
    ax.tick_params(colors="#AAB2BF", labelsize=8)
    ax.grid(color="#343A46", alpha=0.55, linewidth=0.6)
    for spine in ax.spines.values():
        spine.set_color("#343A46")
    ax.legend(loc="upper left", bbox_to_anchor=(0, 0.82),
              facecolor="#202630", edgecolor="#454D5A",
              labelcolor="#FFFFFF", fontsize=8)
    ax.set_xlim(-1, len(candles))
    fig.tight_layout()

    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    path = os.path.join(
        tempfile.gettempdir(), f"signal_{safe_symbol}_{timeframe}.png"
    )
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
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
    last_long_term = 0
    last_daily = 0
    last_news = 0
    last_heatmap = 0

    print("CryptoMarketClub Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â·Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂĂ„Ä…Ă„ËťĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„: Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ă„Ä…Ă‚ÂĂ„Ä…ÄąË‡Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€žĂ„Äľ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂĂ„Ä…Ă˘â‚¬ĹˇÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦, Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸ Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ă„Ä…Ă‚ÂĂ„Ä…Ă‹ĹĄĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦.")
    print("Ä‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬Ë‡Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ă„Ä…Ă‚ÂĂ„Ä…ÄąË‡Ä‚â€žĂ‚ÂĂ„Ä…Ă„ËťÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂĂ„Ä…Ă˘â‚¬Ĺˇ Ă„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚ËĂ˘â€šÂ¬ÄąÄ„ Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¶Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂĂ„Ä…Ă‹ĹĄ Ä‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂÄ‚â€šĂ‚Â; Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ä‚â€žĂ‚ÂÄ‚â€žĂ˘â‚¬Â¦ Ă„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚ËĂ˘â€šÂ¬ÄąÄ„ Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¶Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ 15 Ä‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡; Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂĂ„Ä…Ă˘â‚¬ĹˇÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ä‚â€žĂ‚ÂÄ‚â€žĂ˘â‚¬Â¦ Ă„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚ËĂ˘â€šÂ¬ÄąÄ„ Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¶Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ä‚â€žĂ‚ÂÄ‚â€žĂ˘â‚¬Â¦ Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ă„Ä…Ă‚ÂÄ‚â€šĂ‚Â.")
    print("Ä‚â€žĂ‚ÂĂ„Ä…Ă„â€žÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸ Ă„â€šĂ‹ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚ËĂ˘â€šÂ¬ÄąÄ„ Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¶Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ 15 Ä‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡. Ä‚â€žĂ‚ÂÄ‚ËĂ˘â€šÂ¬ÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ă„Ä…Ă‚ÂĂ„Ä…Ă„â€¦ Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸ Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¶Ä‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸ Ctrl+C.")

    while True:
        now = time.time()
        print("\n" + "=" * 55)
        print("Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹşĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        # Refresh the contract list every 6 hours so new/removed markets are handled.
        if not symbols or int(now) % (6 * 60 * 60) < 60:
            try:
                symbols = get_available_symbols()
                scalp_symbols = symbols[:15]
            except Exception as error:
                print("Ä‚â€žĂ‚ÂĂ„Ä…Ă„â€žÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Âµ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂĂ„Ä…ÄąË‡ Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â±Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂĂ„Ä…ÄąË‡ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂĂ„Ä…Ă„ËťÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹź Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ă„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬Ĺź:", error)

        if now - last_scalp >= SCALP_INTERVAL_SECONDS:
            try:
               scan_modes(
    scalp_symbols,
    [("SCALPING", ["30m"])],
    sent_signals
)
            except Exception as error:
                print("Ä‚â€žĂ‚ÂĂ„Ä…Ă„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â±Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â° Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â´Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂĂ„Ä…Ă˘â‚¬ĹˇÄ‚â€žĂ‚ÂÄ‚â€žĂ„Äľ Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°:", error)
            last_medium = time.time()

        if time.time() - last_long_term >= LONG_INTERVAL_SECONDS:
            try:
                scan_modes(symbols, [("LONG-TERM", ["1h"])], sent_signals)
            except Exception as error:
                print("Long-term scan error:", error)
            last_long_term = time.time()

        if time.time() - last_daily >= DAILY_INTERVAL_SECONDS:
            try:
                scan_modes(symbols, [("DAILY", ["1d"])], sent_signals)
            except Exception as error:
                print("Daily scan error:", error)
            last_daily = time.time()

        if now - last_news >= NEWS_INTERVAL_SECONDS:
            try:
                scan_news(seen_news)
            except Exception as error:
                print("Ä‚â€žĂ‚ÂĂ„Ä…Ă„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â±Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â° Ă„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â° Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€žĂ˘â‚¬Â¦:", error)
            last_news = time.time()

        if now - last_heatmap >= 15 * 60:
            heatmap_path = None
            try:
                heatmap_path = create_market_heatmap(symbols)
                send_telegram_photo(
                    "CryptoMarketClub | Market Heatmap\n"
                    "Crypto market overview for selected USDT pairs.",
                    heatmap_path,
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
        print("\nÄ‚â€žĂ‚ÂÄ‚ËĂ˘â€šÂ¬Ă‚ÂÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡ Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€ąÄąÄ„Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€ąÄąÄ„ Ä‚â€žĂ‚ÂĂ„Ä…Ă„ËťÄ‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ă„Ä…Ă‚ÂĂ„Ä…ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â·Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂÄ‚â€ąĂ˘â‚¬ĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â»Ä‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµÄ‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄ.")
    except Exception as error:
        print("Ä‚â€žĂ‚ÂĂ„Ä…Ă‹â€ˇĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬ÄąË‡Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ă„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă‹â€ˇÄ‚â€žĂ‚ÂÄ‚â€šĂ‚ÂµĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ă„Ä…Ă‚ÂĂ„Ä…Ă„â€¦ Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľĂ„Ä…Ă‚ÂÄ‚â€šĂ‚ÂÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â¸Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â±Ä‚â€žĂ‚ÂĂ„Ä…ÄąĹźÄ‚â€žĂ‚ÂÄ‚â€šĂ‚Â° Ä‚â€žĂ‚ÂĂ„Ä…Ă„ËťĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€žĂ„ÄľÄ‚â€žĂ‚ÂĂ„Ä…Ă˘â‚¬ĹˇĂ„Ä…Ă‚ÂÄ‚ËĂ˘â‚¬ĹˇĂ‚Â¬Ä‚â€žĂ‚ÂÄ‚â€šĂ‚Â°Ä‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄÄ‚â€žĂ‚ÂÄ‚â€žĂ‹ĹĄĂ„Ä…Ă‚ÂÄ‚ËĂ˘â€šÂ¬Ă„â€¦:", error)




