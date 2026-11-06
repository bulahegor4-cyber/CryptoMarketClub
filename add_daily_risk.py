from pathlib import Path
import ast
import json
import math
from datetime import date, datetime

BOT = Path("CryptoMarketClub_restored.py")
BACKUP = Path("CryptoMarketClub_before_daily_risk.py")
TRADES = Path("risk_trades.json")

if not BOT.exists():
    raise SystemExit("ERROR: Main bot file not found.")
if not BACKUP.exists():
    raise SystemExit("ERROR: Backup not found. No changes made.")

source = BOT.read_text(encoding="utf-8-sig")

if "def record_closed_trade(" in source or "def get_daily_risk_status(" in source:
    raise SystemExit("STOP: Functions already exist. No changes made.")

if "RISK_BALANCE_USDT" not in source or "MAX_DAILY_LOSS_PCT" not in source:
    raise SystemExit("STOP: Risk settings not found. No changes made.")

if "import json" not in source:
    source = "import json\n" + source

if "from datetime import" not in source:
    source = "from datetime import date, datetime\n" + source

marker = "def calculate_risk("
if source.count(marker) != 1:
    raise SystemExit("STOP: Could not uniquely find calculate_risk().")

addition = r'''
RISK_TRADES_PATH = str(Path(__file__).resolve().parent / "risk_trades.json")


def record_closed_trade(net_pnl_usdt, symbol="", note=""):
    """Record a manually closed trade result in USDT, after fees."""
    pnl = float(net_pnl_usdt)
    if not math.isfinite(pnl):
        raise ValueError("P&L must be a finite number.")

    path = Path(RISK_TRADES_PATH)
    if path.exists():
        trades = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        trades = []

    if not isinstance(trades, list):
        raise ValueError("risk_trades.json must contain a JSON list.")

    trades.append({
        "date": date.today().isoformat(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "symbol": str(symbol),
        "net_pnl_usdt": pnl,
        "note": str(note),
    })
    path.write_text(
        json.dumps(trades, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return get_daily_risk_status()


def get_daily_risk_status():
    """Summarize today's manually recorded net P&L."""
    path = Path(RISK_TRADES_PATH)
    if path.exists():
        trades = json.loads(path.read_text(encoding="utf-8-sig"))
    else:
        trades = []

    if not isinstance(trades, list):
        raise ValueError("risk_trades.json must contain a JSON list.")

    today = date.today().isoformat()
    pnl = sum(
        float(t.get("net_pnl_usdt", 0))
        for t in trades
        if isinstance(t, dict) and t.get("date") == today
    )
    limit = float(RISK_BALANCE_USDT) * float(MAX_DAILY_LOSS_PCT) / 100

    return {
        "date": today,
        "daily_pnl_usdt": pnl,
        "daily_loss_limit_usdt": limit,
        "limit_reached": pnl <= -limit,
    }


'''

updated = source.replace(marker, addition + marker, 1)

try:
    ast.parse(updated)
except SyntaxError as exc:
    raise SystemExit(f"STOP: Syntax check failed: {exc}. Bot file unchanged.")

BOT.write_text(updated, encoding="utf-8")
print("SUCCESS: Daily risk functions added.")
print("Note: results must be recorded manually; signals are not automatically blocked.")
'''

После сохранения вернись в PowerShell и выполни:

```powershell
python .\add_daily_risk.py