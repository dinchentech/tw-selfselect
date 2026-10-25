"""迴歸測試：用戶自訂策略（`user_strategies.py`）的載入、執行與整合契約。

背景（2026-09-21 由文件審核發現）：根目錄舊的 `test_user_strategies.py` 只印訊息、
**沒有任何 assert**，且結尾**固定**印「請在 config_loader 添加…／請在 selfselect_trader 添加…」
——那兩件事其實早就做完了，害使用者以為還沒接線。本檔把它改成真的會失敗的測試。

測什麼（契約）：
1. `USER_STRATEGY_MAP` 的 4 個策略都存在、都是可呼叫的。
2. 每個策略吃得下標準 OHLCV、回傳同長度 DataFrame 且含 `signal`，值只在 {-1, 0, 1}。
3. 執行時**不得**冒出 pandas `FutureWarning`（歷史包袱：`Series.shift(1).fillna(False)`）。
4. 整合契約：`core.config_loader.STRATEGY_PARAM_KEYS` 登記的鍵＝各策略實際讀取的鍵，
   且 `get_strategy_params()` 真的把 `PC_<代號>` 裡的這些鍵傳得進去（沒登記就會被靜默丟棄）。
5. 實盤接線：`selfselect_trader.py` 有 `STRATEGY_FUNCS.update(USER_STRATEGY_MAP)`。
"""
import sys
import unittest
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from user_strategies import USER_STRATEGY_MAP  # noqa: E402
from core.config_loader import STRATEGY_PARAM_KEYS, get_strategy_params  # noqa: E402

EXPECTED_IDS = {
    "g1_strategy_1": {"buy_price", "sell_price"},
    "g1_strategy_2": {"k_period", "k_threshold", "d_period"},
    "g2_strategy_1": {"lookback", "threshold"},
    "g2_strategy_2": {"ma_period", "volume_ma_period", "volume_mult"},
}


def sample_ohlcv(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame({
        "open": close + rng.normal(0, 0.3, n),
        "high": close + abs(rng.normal(1, 0.3, n)),
        "low": close - abs(rng.normal(1, 0.3, n)),
        "close": close,
        "volume": rng.integers(1000, 10000, n).astype(float),
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))


class TestUserStrategyMap(unittest.TestCase):
    def test_expected_strategies_registered(self):
        self.assertEqual(set(USER_STRATEGY_MAP), set(EXPECTED_IDS))

    def test_all_callable(self):
        for sid, fn in USER_STRATEGY_MAP.items():
            with self.subTest(strategy=sid):
                self.assertTrue(callable(fn))


class TestUserStrategyExecution(unittest.TestCase):
    def test_runs_and_returns_signal_column(self):
        df = sample_ohlcv()
        for sid, fn in USER_STRATEGY_MAP.items():
            with self.subTest(strategy=sid):
                out = fn(df.copy())
                self.assertIsInstance(out, pd.DataFrame)
                self.assertIn("signal", out.columns)
                self.assertEqual(len(out), len(df))
                self.assertTrue(set(out["signal"].unique()) <= {-1, 0, 1},
                                f"{sid} 出現非 -1/0/1 的訊號值")

    def test_no_pandas_futurewarning(self):
        """`shift(1).fillna(False)` 在 pandas 2.x 會噴 FutureWarning（已於 2026-09-21 修）。"""
        df = sample_ohlcv()
        for sid, fn in USER_STRATEGY_MAP.items():
            with self.subTest(strategy=sid):
                with warnings.catch_warnings():
                    warnings.simplefilter("error", FutureWarning)
                    fn(df.copy())  # 有 FutureWarning 就會拋出 → 測試失敗

    def test_parameters_actually_change_signals(self):
        """參數若被忽略（沒登記白名單）就不會改變輸出 —— 這是最容易靜默壞掉的地方。"""
        df = sample_ohlcv()
        out_default = USER_STRATEGY_MAP["g1_strategy_1"](df.copy())
        out_custom = USER_STRATEGY_MAP["g1_strategy_1"](df.copy(), buy_price=99, sell_price=101)
        self.assertFalse(out_default["signal"].equals(out_custom["signal"]),
                         "g1_strategy_1 調 buy_price/sell_price 沒有改變訊號")


class TestIntegrationContract(unittest.TestCase):
    def test_param_keys_whitelist_matches(self):
        for sid, keys in EXPECTED_IDS.items():
            with self.subTest(strategy=sid):
                self.assertEqual(set(STRATEGY_PARAM_KEYS.get(sid, [])), keys,
                                 f"{sid} 的白名單與實際參數不一致（參數會被靜默丟棄）")

    def test_get_strategy_params_passes_registered_keys(self):
        for sid, keys in EXPECTED_IDS.items():
            with self.subTest(strategy=sid):
                cfg = {"strategy": sid, **{k: 1 for k in keys}}
                got = get_strategy_params(cfg, sid)
                self.assertEqual(set(got), keys,
                                 f"{sid}: get_strategy_params 丟掉了 {keys - set(got)}")

    def test_live_trader_wires_user_strategies(self):
        src = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn("from user_strategies import USER_STRATEGY_MAP", src)
        self.assertIn("STRATEGY_FUNCS.update(USER_STRATEGY_MAP)", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
