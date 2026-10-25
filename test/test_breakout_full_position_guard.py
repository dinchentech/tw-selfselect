#!/usr/bin/env python
"""回歸測試：`breakout` 的買入必須是「滿倉不買」（2026-10-06）。

## 問題

實盤 `selfselect_trader.py` 的買入量分兩支：

```python
if (sn not in ['breakout', 'keep_wait']):     # bollinger/vwap/ma_cross
    … held >= target×(1-offset) ⇒ 不重複買入；否則補到 target …
elif (sn == 'breakout'):
    position_size = int(target_amount / px)   # ← 每個買訊都「再買一整個部位」，完全不看已持倉
```

`breakout` 的訊號是**狀態型**：突破區間期間**每天**都會再發一次買訊（實測 2884 在 2026-09 連發 8 個交易日、
2025-12 連發 6 天）。若持有中又遇到買訊且帳戶還有可用資金，就會**重複加碼、超過 `alloc` 上限**
（每檔 6%；4 檔 breakout 就可能多壓 ~3 倍資金）。

## 回測口徑（`scripts/backtest_plan2_monthly_3group.py`）

```python
elif sh == 0 and sig == 1 and bucket.get(sid, 0.0) > 5:   # ← 只有「空倉」才買
    …bucket[sid] = 0.0                                    # 買完桶子歸零 ⇒ 重複買訊也買不動
```

⇒ **回測對所有策略都是「滿倉不買」**，實盤 breakout 是唯一的例外 ⇒ live/backtest 口徑落差。

## 修法

把 `breakout` 併入同一條規則（不再給它專屬分支），滿倉判定抽成純函式 `full_position_topup()`
（`held >= target×(1-BUY_AMOUNT_OFFSET)` ⇒ 回 0 ⇒ 跳過），與 bollinger/vwap/ma_cross 完全一致。

⚠️ 本次沒有實際咬到（4 檔 breakout 的買訊都發生在「尚未被放進 `.env`/尚未持有」之前），
但那是靠風控的資金閘門擋下來的，不是 per-symbol 上限 ⇒ 屬潛在風險。
"""
import ast
import os
import sys
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.live_utils import full_position_topup  # noqa: E402

SRC = ("selfselect_trader.py",)


def _read(rel):
    p = Path(_ROOT) / rel
    return p.read_text(encoding="utf-8") if p.exists() else None


class TestFullPositionTopup(unittest.TestCase):
    """滿倉不買的純函式（兩支分支共用同一條規則）。"""

    def test_empty_position_buys_full_target(self):
        self.assertEqual(full_position_topup(0, 100, 0.02), 100)

    def test_partial_position_tops_up_difference(self):
        self.assertEqual(full_position_topup(40, 100, 0.02), 60)

    def test_full_position_buys_nothing(self):
        self.assertEqual(full_position_topup(100, 100, 0.02), 0)

    def test_over_position_buys_nothing(self):
        self.assertEqual(full_position_topup(150, 100, 0.02), 0)

    def test_within_offset_counts_as_full(self):
        """`held >= target×(1-offset)` 視為足額（與 BUY_AMOUNT_OFFSET 同義）。"""
        self.assertEqual(full_position_topup(99, 100, 0.02), 0)   # 99 ≥ 98
        self.assertEqual(full_position_topup(97, 100, 0.02), 3)   # 97 < 98 ⇒ 補 3

    def test_bad_inputs_do_not_buy(self):
        self.assertEqual(full_position_topup(0, 0, 0.02), 0)
        self.assertEqual(full_position_topup(0, -5, 0.02), 0)
        self.assertEqual(full_position_topup("x", "y", 0.02), 0)

    def test_offset_zero_means_exact_target(self):
        self.assertEqual(full_position_topup(99, 100, 0.0), 1)
        self.assertEqual(full_position_topup(100, 100, 0.0), 0)


class TestLiveWiring(unittest.TestCase):

    def test_breakout_no_longer_has_its_own_sizing_branch(self):
        src = _read(SRC[0])
        tree = ast.parse(src)
        # 找「以 sn == 'breakout' 為條件的 if」——買入量的專屬分支必須消失
        bad = [ast.unparse(n.test) for n in ast.walk(tree)
               if isinstance(n, ast.If) and ast.unparse(n.test).replace(" ", "") == "sn=='breakout'"]
        self.assertFalse(bad, f"breakout 仍有專屬的買入量分支（不看持倉就會重複加碼）：{bad}")

    def test_breakout_not_excluded_from_full_position_rule(self):
        src = _read(SRC[0])
        self.assertNotIn("['breakout', 'keep_wait']", src,
                         "breakout 不可再被排除在『滿倉不買』之外")
        tree = ast.parse(src)
        # 買入量分支的條件必須含 sn 與 keep_wait（＝所有非 keep_wait 策略共用）
        conds = [ast.unparse(n.test) for n in ast.walk(tree)
                 if isinstance(n, ast.If) and "keep_wait" in ast.unparse(n.test)
                 and "sn" in ast.unparse(n.test)]
        self.assertTrue(any("breakout" not in c for c in conds), f"找不到共用的買入量分支：{conds}")

    def test_full_position_guard_present(self):
        src = _read(SRC[0])
        self.assertTrue("full_position_topup" in src, "未使用滿倉判定純函式")
        self.assertTrue("不重複買入" in src, "缺少滿倉時跳過的訊息（守衛）")

    def test_backtest_invariant_is_documented(self):
        """把「回測＝空倉才買」寫成註解，避免日後又被改回『每個買訊都買』。"""
        src = _read(SRC[0])
        self.assertTrue("sh == 0" in src or "空倉" in src,
                        "買入量分支旁應註明回測口徑（空倉才買）")


if __name__ == "__main__":
    unittest.main()
