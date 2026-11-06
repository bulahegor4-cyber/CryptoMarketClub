from pathlib import Path

p = Path("CryptoMarketClub_restored.py")
s = p.read_text(encoding="utf-8-sig")

marker = "    price = closes[-1]\n"
insert = '''    smc = analyze_smc(candles)
    print("SMC | {} {}: direction={}, BOS={}, sweep={}, FVG={}".format(
        symbol, timeframe, smc["direction"], smc["bos"],
        smc["liquidity_sweep"], smc["fvg"]
    ))
'''

if "smc = analyze_smc(candles)" in s:
    print("SMC call already exists; no changes made.")
elif marker not in s:
    print("ERROR: insertion point not found; no changes made.")
else:
    p.write_text(s.replace(marker, insert + marker, 1), encoding="utf-8")
    print("SMC analysis added.")
