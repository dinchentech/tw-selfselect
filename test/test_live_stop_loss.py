#!/usr/bin/env python
"""回歸測試：**實盤**硬停損（2026-11-20，v1.1.44）。

## 背景（為什麼突然要加）

`core.backtest_rules.stop_hit()` 從 2026-09-16 就在，但**只有回測腳本在用**，
`selfselect_trader.py` 的實盤路徑一處都沒有引用 ⇒ 實盤沒有任何停損機制。

2026-11-18 追零成交時撞到實例（見 `cairn/LOG.md` 同日條目）：

```
2408 608 股 @ 411、11/18 收 325（約 −52k／−21%）
11/20 09:00 報價 276.50 ⇒ −32.7%（約 −82k）
```

鎖定的策略是 Bollinger 反轉，賣訊條件是「收盤 > 上軌 **且** RSI > 70」
⇒ 一路陰跌時結構上**永遠不會**給賣訊，部位只能放到換股日。停泊的 0050 同理
（停泊釋出只認「要買股票」，不看損益）。

## 這支測試釘住什麼

1. 純函式：`stop_loss_pct_now()`（每次讀 env、0＝停用）與 `avg_entry_cost()`
   （分帳本 → 現有部位均價，賣出後要按比例反映）。
2. 接線不變式（原始碼層級）：停損必須**只在 13:25–13:30 窗口**判定、必須在
   「策略訊號之後、下單之前」、必須全數出場、必須穿過 PROFIT_MARGIN 的防 churn 門檻
   （那個門檻是省手續費用的，不是風控——擋住停損就等於沒有停損）。
3. `.env.example.txt` 有說明 `STOP_LOSS_PCT`（0＝停用）⇒ 換版本身不動任何倉位。
"""
import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent
SRC = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")


def _module_func(name: str) -> str:
    """取**模組層**函式的原始碼（不含 docstring 以外的處理：整段拿）。"""
    tree = ast.parse(SRC)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SRC, node) or ""
    raise AssertionError(f"selfselect_trader.py 找不到模組層函式 {name}()")


def _sandbox():
    """把兩個純函式 exec 進獨立 namespace（不 import 主程式，避免拉進 load_dotenv／broker）。"""
    from core.backtest_rules import stop_hit, stop_loss_env
    ns = {"stop_hit": stop_hit, "stop_loss_env": stop_loss_env}
    for fn in ("stop_loss_pct_now", "avg_entry_cost"):
        exec(_module_func(fn), ns)
    return ns


class StopLossKnobTest(unittest.TestCase):
    """`STOP_LOSS_PCT` 語意必須與回測完全一致：0／未設＝停用。"""

    def test_unset_means_disabled(self):
        ns = _sandbox()
        env = {k: v for k, v in os.environ.items() if k != "STOP_LOSS_PCT"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(ns["stop_loss_pct_now"](), 0.0)

    def test_env_value_is_read(self):
        ns = _sandbox()
        with patch.dict(os.environ, {"STOP_LOSS_PCT": "10"}):
            self.assertEqual(ns["stop_loss_pct_now"](), 10.0)

    def test_broken_value_falls_back_to_disabled(self):
        ns = _sandbox()
        with patch.dict(os.environ, {"STOP_LOSS_PCT": "abc"}):
            self.assertEqual(ns["stop_loss_pct_now"](), 0.0)

    def test_trigger_matches_backtest_rule(self):
        """同一組數字，實盤（stop_hit）與回測必須給同一個答案。"""
        ns = _sandbox()
        stop_hit = ns["stop_hit"]
        entry, pct = 411.0, 10.0
        self.assertFalse(stop_hit(411.0 * 0.91, entry, pct), "−9% 不該觸發")
        self.assertTrue(stop_hit(411.0 * 0.90, entry, pct), "剛好 −10% 要觸發（回測口徑 ≤）")
        self.assertTrue(stop_hit(276.5, entry, pct), "2408 實例 −33% 必須觸發")


class AvgEntryCostTest(unittest.TestCase):
    """停損的「均價」必須是**現有部位**的均價（分帳本，賣出後按比例扣減）。"""

    def setUp(self):
        self.ns = _sandbox()
        self.fn = self.ns["avg_entry_cost"]

    def test_simple_average(self):
        alloc = {"2408": {"total_buy_shares": 608, "total_buy_cost": 608 * 411.0}}
        self.assertAlmostEqual(self.fn(alloc, "2408"), 411.0)

    def test_partial_sell_reduces_cost_basis(self):
        """賣掉一半（sell_stock_allocation 會按比例扣減）⇒ 均價不變。"""
        alloc = {"2408": {"total_buy_shares": 304, "total_buy_cost": 304 * 411.0}}
        self.assertAlmostEqual(self.fn(alloc, "2408"), 411.0)

    def test_no_position_returns_zero(self):
        self.assertEqual(self.fn({"2408": {"total_buy_shares": 0, "total_buy_cost": 0.0}}, "2408"), 0.0)
        self.assertEqual(self.fn({}, "2408"), 0.0)
        self.assertEqual(self.fn(None, "2408"), 0.0)

    def test_broken_values_return_zero(self):
        alloc = {"2408": {"total_buy_shares": "x", "total_buy_cost": "y"}}
        self.assertEqual(self.fn(alloc, "2408"), 0.0)


class StopLossWiringTest(unittest.TestCase):
    """接線不變式（原始碼層級 —— 停損埋在 `main()` 的長迴圈裡，不容易直接呼叫）。"""

    def _block(self) -> str:
        start = SRC.index("# ── 實盤硬停損（2026-11-20，v1.1.44；說明見模組層")
        end = SRC.index("if (signal != 0):", start)
        return SRC[start:end]

    def test_rules_shared_with_backtest(self):
        self.assertIn("from core.backtest_rules import stop_hit, stop_loss_env", SRC,
                      "實盤必須與回測共用同一支 stop_hit／stop_loss_env")

    def test_only_in_close_order_window(self):
        blk = self._block()
        self.assertIn("_close_order_window", blk,
                      "停損只在 13:25–13:30 收盤前窗口判定（與日K策略、回測同口徑）")
        self.assertIn("_stop_pct > 0", blk, "0＝停用必須真的不執行")

    def test_before_order_dispatch_and_full_exit(self):
        blk = self._block()
        self.assertIn("signal = -1", blk)
        self.assertIn("position_size = _held_stop", blk, "停損＝全數出場")
        # 位置：必須在派送 `if (signal != 0):` **之前**（否則覆蓋不了策略訊號）
        self.assertLess(SRC.index(blk), SRC.index("if (signal != 0):"))

    def test_requires_position_and_cost_basis(self):
        blk = self._block()
        self.assertIn("_held_stop > 0", blk, "沒持股不該觸發")
        self.assertIn("avg_entry_cost(stock_alloc, symbol)", blk)
        self.assertIn("stop_hit(px, _entry_stop, _stop_pct)", blk)

    def test_notifies_once_per_symbol_per_day(self):
        blk = self._block()
        self.assertIn("_stop_notified.get(symbol) != today_str", blk)
        self.assertIn("_stop_notified[symbol] = today_str", blk)
        self.assertIn("_stop_notified = {}", SRC, "去重字典必須初始化")

    def test_profit_margin_must_not_block_stop(self):
        """PROFIT_MARGIN 是防 churn（省手續費），不是風控 ⇒ 停損要穿過它。"""
        self.assertIn("(not _stop_exit)", SRC)
        idx = SRC.index("(PROFIT_MARGIN > 0) and (action == 'SELL')")
        self.assertIn("(not _stop_exit)", SRC[idx:idx + 200])

    def test_stop_is_announced_to_telegram(self):
        blk = self._block()
        self.assertIn("send_telegram_message", blk)
        self.assertIn("硬停損", blk)


class EnvDocsTest(unittest.TestCase):

    def test_env_example_documents_knob(self):
        src = (_ROOT / ".env.example.txt").read_text(encoding="utf-8")
        self.assertIn("STOP_LOSS_PCT", src, ".env.example.txt 必須說明這個旋鈕")

    def test_default_off_documented(self):
        src = (_ROOT / ".env.example.txt").read_text(encoding="utf-8")
        idx = src.index("STOP_LOSS_PCT")
        window = src[max(0, idx - 400):idx + 400]
        self.assertIn("0", window)
        self.assertTrue(("停用" in window) or ("關" in window), "必須寫清楚 0＝停用")


if __name__ == "__main__":
    unittest.main()
