import json
from datetime import date, datetime
from pathlib import Path

TRADES_FILE = Path(__file__).resolve().parent / "risk_trades.json"
BALANCE_USDT = 1000.0
MAX_DAILY_LOSS_PCT = 3.0


def load_trades():
    if not TRADES_FILE.exists():
        return []
    with TRADES_FILE.open("r", encoding="utf-8-sig") as file:
        trades = json.load(file)
    if not isinstance(trades, list):
        raise ValueError("risk_trades.json must contain a list")
    return trades


def record_closed_trade(net_pnl_usdt, symbol="", note=""):
    pnl = float(net_pnl_usdt)
    trades = load_trades()
    trades.append({
        "date": date.today().isoformat(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "symbol": str(symbol),
        "net_pnl_usdt": pnl,
        "note": str(note),
    })
    TRADES_FILE.write_text(
        json.dumps(trades, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return daily_status()


def daily_status():
    today = date.today().isoformat()
    trades = load_trades()
    pnl = sum(
        float(trade.get("net_pnl_usdt", 0))
        for trade in trades
        if isinstance(trade, dict) and trade.get("date") == today
    )
    loss_limit = BALANCE_USDT * MAX_DAILY_LOSS_PCT / 100

    return {
        "date": today,
        "daily_pnl_usdt": round(pnl, 4),
        "daily_loss_limit_usdt": round(loss_limit, 4),
        "limit_reached": pnl <= -loss_limit,
    }


if __name__ == "__main__":
    print(json.dumps(daily_status(), indent=2, ensure_ascii=False))