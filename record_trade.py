"""Manually log a closed trade so the bot's daily loss guard has real PnL data.

Run from the project folder with:
    py record_trade.py

Enter net PnL after fees: negative for a loss, positive for a profit.
This does not connect to an exchange or execute orders.
"""
from daily_risk import record_closed_trade


def main():
    print("CryptoMarketClub | Closed trade journal")
    symbol = input("Symbol (e.g. BTC-USDT): ").strip().upper()
    if not symbol:
        symbol = "UNKNOWN"

    raw_pnl = input("Net PnL in USDT after fees (e.g. -12.50 or 8.20): ").strip()
    try:
        pnl = float(raw_pnl.replace(",", "."))
    except ValueError:
        raise SystemExit("Invalid PnL. Enter a number such as -12.50.")

    if not pnl == pnl or abs(pnl) == float("inf"):
        raise SystemExit("PnL must be a finite number.")

    note = input("Optional note (Enter to skip): ").strip()
    status = record_closed_trade(pnl, symbol=symbol, note=note)

    print("\nTrade saved.")
    print(f"Today's net PnL: {status['daily_pnl_usdt']:.2f} USDT")
    print(f"Daily loss limit: -{status['daily_loss_limit_usdt']:.2f} USDT")
    if status["limit_reached"]:
        print("DAILY LOSS LIMIT REACHED: new signals will be paused by the bot.")
    else:
        remaining = status["daily_loss_limit_usdt"] + status["daily_pnl_usdt"]
        print(f"Loss allowance remaining before lockout: {max(0.0, remaining):.2f} USDT")


if __name__ == "__main__":
    main()
