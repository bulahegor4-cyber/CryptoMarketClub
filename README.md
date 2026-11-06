# CryptoMarketClub

Telegram market-analysis bot for BingX USDT perpetual markets.

## Current scope

- Crypto futures market scanning and technical signal publishing.
- 30-minute scalping scan, 15-minute medium-term scan, 1-hour long-term scan, and 1-day scan.
- EMA, RSI, MACD, ATR, volume-ratio and simplified SMC filters.
- Telegram forum routing for signals, news, altcoins, and macro news.
- RSS news intake and a market heatmap.
- Signal generation only: **the bot does not place exchange orders**.

Forex and gold scanning are not implemented in this version.

## Local setup

1. Keep your Telegram bot token in a local `.env` file. Never commit `.env` or share the token.
2. Configure the forum topic IDs in `.env`: `TELEGRAM_TOPIC_SIGNALS_ID`, `TELEGRAM_TOPIC_NEWS_ID`, `TELEGRAM_TOPIC_ALTCOINS_ID`, `TELEGRAM_TOPIC_MACRO_ID`, and `TELEGRAM_TOPIC_GOLD_FOREX_ID`.
3. Install the Python dependencies used by the project: `requests` and `matplotlib`.
4. Run `py CryptoMarketClub_channel.py`.

## Risk journal and daily lockout

The signal size estimate currently uses a $1,000 reference balance and 10% risk per trade ($100), with an estimated round-trip fee. **10% risk per trade is extremely aggressive**; paper-trade first and consider a substantially smaller risk setting before using signals with real funds.

The daily loss guard reads closed-trade results from `risk_trades.json` and blocks new signal scans after the configured 3% daily loss threshold. Since this bot does not know whether a user actually entered a published signal, results must be logged manually:

```powershell
py record_trade.py
```

Enter net PnL in USDT after fees (negative for a loss, positive for a profit). If trades are not logged, the daily loss guard cannot know the real account PnL and must not be treated as an automatic account-level protection.

## Important

- Signals are analytical estimates, not guarantees or financial advice.
- Stop-loss execution, slippage, funding, leverage and exchange fees can make actual results differ from estimates.
- Test all changes in a demo/paper environment before relying on them.
