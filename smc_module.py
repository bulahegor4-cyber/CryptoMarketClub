
def analyze_smc(candles, lookback=30):
    """Simple SMC approximation using closed candles only."""
    neutral = {
        "direction": "NEUTRAL",
        "bos": None,
        "mss": None,
        "liquidity_sweep": None,
        "fvg": None,
        "swing_high": None,
        "swing_low": None,
        "reason": "Waiting for confirmation",
    }

    if not candles or len(candles) < lookback + 8:
        neutral["reason"] = "Not enough candles"
        return neutral

    bars = candles  # Caller already removes the possibly forming candle.

    def val(bar, key):
        try:
            return float(bar[key])
        except (KeyError, TypeError, ValueError):
            return None

    recent = bars[-(lookback + 5):]

    # Validate OHLC data.
    for bar in recent:
        if any(val(bar, key) is None for key in ("open", "high", "low", "close")):
            neutral["reason"] = "Invalid candle data"
            return neutral

    # Levels are calculated from older candles, not the signal candles.
    reference = recent[:-4]
    swing_high = max(val(c, "high") for c in reference)
    swing_low = min(val(c, "low") for c in reference)

    # Search the last three closed candles for a sweep.
    sweep = None
    sweep_index = None

    for i in range(len(recent) - 3, len(recent)):
        bar = recent[i]
        high, low, close = val(bar, "high"), val(bar, "low"), val(bar, "close")

        if low < swing_low and close > swing_low:
            sweep = "BULLISH"
            sweep_index = i
        elif high > swing_high and close < swing_high:
            sweep = "BEARISH"
            sweep_index = i

    # Look for a structure break after the sweep.
    bos = None
    if sweep is not None and sweep_index is not None:
        for i in range(sweep_index + 1, len(recent)):
            bar = recent[i]
            close = val(bar, "close")
            previous_close = val(recent[i - 1], "close")

            if sweep == "BULLISH" and close > swing_high and previous_close <= swing_high:
                bos = "BULLISH"
                break
            if sweep == "BEARISH" and close < swing_low and previous_close >= swing_low:
                bos = "BEARISH"
                break

    # Three-candle fair value gap.
    a, b, c = recent[-3], recent[-2], recent[-1]
    fvg = None
    if val(c, "low") > val(a, "high"):
        fvg = "BULLISH"
    elif val(c, "high") < val(a, "low"):
        fvg = "BEARISH"

    direction = "NEUTRAL"

    if sweep is None:
        reason = "No liquidity sweep detected in the last three closed candles"
    elif bos is None:
        reason = f"{sweep.title()} liquidity sweep detected, but no confirming BOS"
    elif bos != sweep:
        reason = f"Liquidity sweep direction ({sweep}) conflicts with BOS ({bos})"
    else:
        direction = sweep
        reason = f"{sweep.title()} liquidity sweep followed by structure break"

    return {
        "direction": direction,
        "bos": bos,
        "mss": bos,
        "liquidity_sweep": sweep,
        "fvg": fvg,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "reason": reason,
    }
