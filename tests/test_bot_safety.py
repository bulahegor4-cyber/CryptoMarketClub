import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import daily_risk
from smc_module import analyze_smc
from CryptoMarketClub_channel import calculate_risk, clean_news_text


class DailyRiskTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.trades_path = Path(self.temp_dir.name) / "risk_trades.json"
        self.path_patch = patch.object(daily_risk, "TRADES_FILE", self.trades_path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_loss_at_daily_limit_triggers_lockout(self):
        status = daily_risk.record_closed_trade(-30.0, symbol="BTC-USDT")
        self.assertTrue(status["limit_reached"])
        self.assertEqual(status["daily_pnl_usdt"], -30.0)

    def test_profit_does_not_trigger_lockout(self):
        status = daily_risk.record_closed_trade(12.5, symbol="ETH-USDT")
        self.assertFalse(status["limit_reached"])
        self.assertEqual(status["daily_pnl_usdt"], 12.5)

    def test_non_finite_pnl_is_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    daily_risk.record_closed_trade(value)
        self.assertFalse(self.trades_path.exists())


class RiskSizingTests(unittest.TestCase):
    def test_long_risk_is_calculated(self):
        result = calculate_risk(100, 95, 110, "LONG")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["risk_usdt"], 100.0)
        self.assertGreater(result["position_notional"], 0)

    def test_short_risk_is_calculated(self):
        result = calculate_risk(100, 105, 90, "SHORT")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["risk_usdt"], 100.0)

    def test_invalid_price_order_is_rejected(self):
        self.assertIsNone(calculate_risk(100, 105, 110, "LONG"))
        self.assertIsNone(calculate_risk(100, 95, 90, "SHORT"))
        self.assertIsNone(calculate_risk(100, 95, 110, "HOLD"))


class NewsTextTests(unittest.TestCase):
    def test_whitespace_is_collapsed(self):
        self.assertEqual(clean_news_text("hello\n\t  world"), "hello world")

    def test_html_is_removed_and_entities_are_decoded(self):
        self.assertEqual(clean_news_text("<p>BTC &amp; ETH</p>"), "BTC & ETH")


class SMCAnalysisTests(unittest.TestCase):
    @staticmethod
    def candle(open_price=100, high=105, low=95, close=100):
        return {
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1000,
            "time": 1,
        }

    def test_bullish_sweep_bos_and_fvg_confirm(self):
        candles = [self.candle() for _ in range(18)]
        candles[-3] = self.candle(99, 101, 94, 96)
        candles[-2] = self.candle(100, 107, 99, 106)
        candles[-1] = self.candle(104, 108, 102, 105)

        result = analyze_smc(candles, lookback=10)

        self.assertEqual(result["direction"], "BULLISH")
        self.assertEqual(result["liquidity_sweep"], "BULLISH")
        self.assertEqual(result["bos"], "BULLISH")
        self.assertEqual(result["fvg"], "BULLISH")

    def test_no_sweep_stays_neutral(self):
        result = analyze_smc([self.candle() for _ in range(18)], lookback=10)
        self.assertEqual(result["direction"], "NEUTRAL")
        self.assertIsNone(result["liquidity_sweep"])

    def test_invalid_candle_data_stays_neutral(self):
        candles = [self.candle() for _ in range(18)]
        candles[-1] = {"open": 100, "high": None, "low": 95, "close": 100}
        result = analyze_smc(candles, lookback=10)
        self.assertEqual(result["direction"], "NEUTRAL")
        self.assertEqual(result["reason"], "Invalid candle data")


if __name__ == "__main__":
    unittest.main()
