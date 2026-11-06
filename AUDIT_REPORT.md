# CryptoMarketClub — technical audit

Audit date: 2026-11-06  
Audited refs: `main` at `9d5f629`; `stabilize-scanner-schedule` at `9e467344`  
Scope: read-only review of the GitHub repository and draft PR #1. No exchange orders were placed and no secrets were accessed.

## Executive summary

The repository contains a signal-publishing bot for BingX USDT perpetual markets. It does not execute exchange orders. PR #1 improves the scanner schedule and adds a manual closed-trade journal, and its Python syntax-check workflow passed. The PR should remain a draft until the outstanding issues below are addressed and tested.

## Findings

### Critical safety and release blockers

1. **No repository ignore rules on `main`.** A local `.env` exists in the user's working directory and contains credentials/configuration. Without a `.gitignore`, a careless `git add .` could publish secrets. This audit branch adds ignore rules for `.env`, runtime state, bytecode, and generated artifacts. Keep the real token local; use a redacted `.env.example` only if needed.
2. **Risk per signal is 10% of the $1,000 reference balance ($100).** This is extremely aggressive. The daily lockout is configured at 3% ($30), so the planned per-trade risk is more than three times the daily limit. This must not be treated as a safe live-trading configuration. Do not enable automatic order execution.
3. **Daily PnL protection is manual, not account-connected.** The bot reads `risk_trades.json` through `daily_risk.py`; users must manually record closed trades using `record_trade.py`. The bot cannot know whether a Telegram signal was traded or read actual BingX account PnL. The guard therefore cannot guarantee account-level loss protection.

### High-priority correctness issues

4. **Russian text is corrupted (mojibake) in the active scanner file.** This affects signal labels, diagnostic output, and error messages. The corruption is present in both `main` and the scanner-schedule branch; PR #1 fixes one malformed call site but does not repair the wider text.
5. **The six-hour market refresh condition can refresh repeatedly for a full minute.** The loop checks `int(now) % (6 * 60 * 60) < 60` while sleeping only five seconds. During the first minute of each six-hour boundary, this condition remains true and can trigger repeated contract/ticker API calls. Replace it with an elapsed-time guard using a `last_symbols_refresh` timestamp.
6. **The main branch scheduler does not actually run the medium-term scan.** In `main`, the scalp scan's exception/follow-up area updates `last_medium` without calling a medium scan. PR #1 adds the missing 15-minute medium-term scan and is an improvement.
7. **Market filtering is not a strict crypto-asset whitelist.** The current filter requires a USDT suffix, an alphanumeric base symbol, contract status, minimum quote volume, and a maximum spread. This excludes many obvious non-crypto symbols but can still admit unusual alphanumeric instruments that happen to be listed as USDT contracts. Validate contract metadata/category and maintain explicit exclusions before broadening coverage.
8. **PUMP is conditional, not guaranteed.** It is prioritized only if BingX lists `PUMP-USDT` and it passes the same liquidity/spread filters. The current logic does not discover every new listing or guarantee that a memecoin is scanned.

### Strategy and scope limitations

9. **SMC is a simplified heuristic.** It requires a recent sweep, a subsequent BOS, and a matching three-candle FVG. This is restrictive and is not a complete institutional SMC model; neutral results are expected. It needs deterministic unit tests and historical validation before tuning.
10. **Forex and gold are not implemented.** The README correctly states that the current bot scans BingX USDT perpetual crypto markets only. The existence of a Telegram topic ID does not mean a scanner exists.
11. **News classification is keyword-based.** It is a first-pass filter, not an AI/news-impact model. False positives and missed stories are possible.
12. **Text normalization bug to verify/fix.** `clean_news_text` currently uses a raw regex pattern written as `r"\\s+"`; this matches a literal backslash followed by `s`, not ordinary whitespace. The intended pattern is `r"\s+"`.

## PR #1 assessment

PR #1 (`stabilize-scanner-schedule` → `main`) is a useful partial stabilization:
- Adds the missing 15-minute medium-term scan.
- Makes the 30-minute scan run on a 60-second scheduler.
- Adds a manual trade journal.
- Adds README scope/risk documentation and a Python compile workflow.
- The observed GitHub Actions syntax-check run completed successfully.

However, it does not resolve the refresh-loop issue, widespread mojibake, or the risk/configuration limitations. Keep PR #1 in draft until those are addressed and the active local project is reconciled with the repository.

## Safe implementation order

1. Keep `.env` and runtime state files out of Git; rotate any bot token that has ever been pasted into a chat or public location.
2. Reconcile the user's local `C:\\CryptoBot` with the GitHub feature branch without overwriting the original folder.
3. Fix the six-hour refresh timer and add tests for scheduler cadence.
4. Repair Russian text from known-good source strings; do not apply blind encoding conversions to already-corrupted text.
5. Fix whitespace normalization and add tests.
6. Add market-symbol filtering tests, including unusual non-crypto contract names and PUMP availability/liquidity cases.
7. Add unit tests for risk sizing, daily lockout, SMC edge cases, duplicate signal suppression, and Telegram topic fallback.
8. Review risk settings separately. Do not silently change the user's requested settings; require paper trading and explicit review before any live-use recommendation.
9. Keep Forex/gold as a separate future module with its own data source and tests; do not label the current crypto scanner as supporting them.

## Operational boundary

This repository version generates analysis and Telegram messages only. It does not submit orders. No live trading, credential access, `.env` upload, merge to `main`, or exchange-order automation was performed as part of this audit.
