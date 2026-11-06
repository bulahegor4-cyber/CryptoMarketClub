import requests


def get_json(url, params=None):
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if not isinstance(data, (dict, list)):
        raise ValueError("API вернул неожиданный формат")

    return data

def get_volumes():
    volumes = {}

    # Binance: объём торгов в USDT за 24 часа
    data = get_json("https://api.binance.com/api/v3/ticker/24hr")
    for item in data:
        symbol = item.get("symbol", "")
        if symbol.endswith("USDT"):
            try:
                volumes.setdefault(symbol, {})["Binance Spot"] = float(
                    item.get("quoteVolume", 0)
                )
            except (TypeError, ValueError):
                pass

    # Bybit: все спотовые тикеры
    data = get_json(
        "https://api.bybit.com/v5/market/tickers",
        params={"category": "spot"},
    )
    if data.get("retCode") != 0:
        raise RuntimeError(f"Bybit API error: {data.get('retMsg')}")

    for item in data.get("result", {}).get("list", []):
        symbol = item.get("symbol", "")
        if symbol.endswith("USDT"):
            try:
                volumes.setdefault(symbol, {})["Bybit Spot"] = float(
                    item.get("turnover24h", 0)
                )
            except (TypeError, ValueError):
                pass

    # BingX: объём торгов в USDT за 24 часа
    data = get_json(
        "https://open-api.bingx.com/openApi/spot/v1/ticker/24hr"
    )
    if str(data.get("code")) not in ("0", "200"):
        raise RuntimeError(f"BingX API error: {data.get('msg', data)}")

    for item in data.get("data", []):
        symbol = item.get("symbol", "").replace("-", "")
        if symbol.endswith("USDT"):
            try:
                volumes.setdefault(symbol, {})["BingX Spot"] = float(
                    item.get("quoteVolume", 0)
                )
            except (TypeError, ValueError):
                pass

    return volumes


if __name__ == "__main__":
    result = get_volumes()
    print("Получены объёмы для пар:", len(result))
    for symbol in ("BTCUSDT", "ETHUSDT"):
        print(symbol, result.get(symbol, {}))
