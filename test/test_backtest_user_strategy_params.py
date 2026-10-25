"""回歸測試：backtest.py 的 CLI 參數白名單必須與策略實際參數一致（使用者自訂策略）

事故（2026-09-21 由文件審核發現）：
  backtest.py 的 STRATEGY_CONFIG / STRATEGY_PARAMS 對 `g1_strategy_1` 仍寫
  `fast_period` / `slow_period`，但該策略實際是 `user_strategies.price_band`，
  只吃 `buy_price` / `sell_price`（core/config_loader.STRATEGY_PARAM_KEYS 亦如此登記）。
  ⇒ `--strategy g1_strategy_1 --fast_period 10` 會被 `**kwargs` 吸收後**靜默無效**，
     `--buy_price 240` 則直接 argparse 失敗（unrecognized arguments）。
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backtest  # noqa: E402
from core import config_loader  # noqa: E402

# 使用者自訂策略：CLI 可調參數必須與 config_loader 白名單（實盤 PC_ 用同一份）一致
USER_STRATEGIES = ["g1_strategy_1", "g1_strategy_2", "g2_strategy_1", "g2_strategy_2"]


class TestBacktestUserStrategyParams(unittest.TestCase):
    def test_cli_params_match_config_loader_whitelist(self):
        """STRATEGY_PARAMS 的鍵＝config_loader 白名單，否則 CLI 參數會被靜默丟棄。"""
        for sid in USER_STRATEGIES:
            with self.subTest(strategy=sid):
                cli_keys = set(backtest.STRATEGY_PARAMS.get(sid, {}))
                allowed = set(config_loader.STRATEGY_PARAM_KEYS.get(sid, []))
                self.assertEqual(
                    cli_keys, allowed,
                    f"{sid}: CLI 參數 {sorted(cli_keys)} != 白名單 {sorted(allowed)}")

    def test_cli_defaults_match_strategy_config_defaults(self):
        for sid in USER_STRATEGIES:
            with self.subTest(strategy=sid):
                cfg_defaults = backtest.STRATEGY_CONFIG[sid]["params"]
                cli_defaults = {k: v["default"]
                                for k, v in backtest.STRATEGY_PARAMS[sid].items()}
                self.assertEqual(cfg_defaults, cli_defaults,
                                 f"{sid}: STRATEGY_CONFIG 與 STRATEGY_PARAMS 預設值不一致")

    def test_g1_strategy_1_uses_price_band_params(self):
        """g1_strategy_1 就是 price_band —— 參數只能是 buy_price / sell_price。"""
        self.assertEqual(set(backtest.STRATEGY_PARAMS["g1_strategy_1"]),
                         {"buy_price", "sell_price"})

    def test_price_band_params_actually_reach_the_strategy(self):
        """端到端：CLI 給的 buy_price/sell_price 真的改變訊號（不是被吸收後丟掉）。"""
        import pandas as pd

        df = pd.DataFrame({
            "open": [300.0, 260.0, 245.0, 270.0, 200.0],
            "high": [300.0, 260.0, 245.0, 270.0, 200.0],
            "low": [300.0, 260.0, 245.0, 270.0, 200.0],
            "close": [300.0, 260.0, 245.0, 270.0, 200.0],
            "volume": [1000] * 5,
        })
        fn = backtest.STRATEGY_CONFIG["g1_strategy_1"]["func"]
        default_sig = list(fn(df.copy())["signal"])
        tight_sig = list(fn(df.copy(), buy_price=240, sell_price=290)["signal"])
        self.assertNotEqual(default_sig, tight_sig,
                            "調 buy_price/sell_price 沒有改變訊號 → 參數沒生效")

    def test_cli_accepts_real_param_names(self):
        """真正的 parser 必須有 --buy_price／--sell_price（`--help` 走完 argparse，不跑回測）。"""
        import subprocess
        out = subprocess.run(
            [sys.executable, str(ROOT / "backtest.py"), "--help"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertIn("--buy_price", out.stdout)
        self.assertIn("--sell_price", out.stdout)


if __name__ == "__main__":
    unittest.main()
