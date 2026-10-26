"""迴歸測試：`keep_wait` 分層停利支援「絕對價位」寫法（`tp_tiers` 的 `price`）。

背景（2026-10-26）：投影片 W1 第 11 頁示範「250 以下買、280 以上賣」是用自訂策略
`g1_strategy_1`（`buy_price`/`sell_price`）。為了讓 `keep_wait` 也能做同一件事，
`selfselect_trader.keep_wait_tier_hit()` 增加 `price` 分支：

    {"pct": 15, "ratio": 50}     # 舊寫法：相對均價漲幅
    {"price": 280, "ratio": 50}  # 新寫法：現價 >= 280

測什麼：
1. `price` 分層在「現價 ≥ 價位」才觸發（等於不觸發、差 0.1 元也不觸發）。
2. 已觸發過的層（`fired`）不再重複觸發，後面的層照樣可以觸發。
3. 舊的 `pct` 寫法行為不變。
4. 兩種寫法可混用，依陣列順序決定先觸發哪一層。
5. 壞資料（非 dict、非數字、缺欄位）不會拋錯，只是被跳過。
6. 實盤接線：`selfselect_trader.py` 的停利區塊真的呼叫了 `keep_wait_tier_hit`。
"""
import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TRADER_PATH = ROOT / "selfselect_trader.py"


def _load_helper():
    """只執行 `keep_wait_tier_hit` 的原始碼，避免匯入整支交易程式（會連券商/網路）。"""
    src = TRADER_PATH.read_text(encoding="utf-8")
    start = src.index("def keep_wait_tier_hit")
    end = src.index("\nfrom core.live_broker import")
    ns = {}
    exec(src[start:end], ns)  # noqa: S102 - 測試專用
    return ns["keep_wait_tier_hit"]


class KeepWaitPriceTierTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hit = staticmethod(_load_helper())

    # ── 1. price 門檻 ──
    def test_price_tier_needs_price_at_or_above_threshold(self):
        tiers = [{"price": 280, "ratio": 50}]
        self.assertIsNone(self.hit(tiers, [], 279.9, 50.0))
        self.assertIsNotNone(self.hit(tiers, [], 280.0, 0.0))
        self.assertIsNotNone(self.hit(tiers, [], 300.0, 0.0))

    def test_price_tier_ignores_profit_pct(self):
        """絕對價位只看現價——均價很低、獲利 % 很高也不該觸發。"""
        tiers = [{"price": 280, "ratio": 50}]
        self.assertIsNone(self.hit(tiers, [], 250.0, 400.0))

    # ── 2. fired 記錄 ──
    def test_fired_tier_is_not_retriggered(self):
        tiers = [{"price": 280, "ratio": 50}, {"price": 320, "ratio": 100}]
        # 第 0 層已觸發，但現價還沒到第 1 層的 320 → 不動作
        self.assertIsNone(self.hit(tiers, [0], 290.0, 0.0))
        self.assertEqual(self.hit(tiers, [0], 320.0, 0.0), (1, tiers[1]))
        self.assertIsNone(self.hit(tiers, [0, 1], 400.0, 0.0))

    # ── 3. 舊 pct 寫法不變 ──
    def test_pct_tier_behaviour_unchanged(self):
        tiers = [{"pct": 15, "ratio": 50}]
        self.assertIsNone(self.hit(tiers, [], 100.0, 14.9))
        self.assertIsNotNone(self.hit(tiers, [], 100.0, 15.0))
        # 缺 pct 時沿用預設 15%
        self.assertIsNone(self.hit([{"ratio": 50}], [], 100.0, 14.0))
        self.assertIsNotNone(self.hit([{"ratio": 50}], [], 100.0, 15.0))

    # ── 4. 混用時依陣列順序 ──
    def test_mixed_tiers_follow_list_order(self):
        tiers = [{"pct": 10, "ratio": 30}, {"price": 300, "ratio": 70}]
        self.assertEqual(self.hit(tiers, [], 100.0, 11.0), (0, tiers[0]))
        # 第 0 層已觸發 → 換看第 1 層（價位）
        self.assertIsNone(self.hit(tiers, [0], 299.0, 11.0))
        self.assertEqual(self.hit(tiers, [0], 300.0, 11.0), (1, tiers[1]))

    # ── 5. 壞資料容錯 ──
    def test_bad_payloads_are_skipped(self):
        self.assertIsNone(self.hit([{"price": "abc"}], [], 999.0, 99.0))
        self.assertIsNone(self.hit([{"pct": None}], [], 999.0, 99.0))
        self.assertIsNone(self.hit(["oops"], [], 999.0, 99.0))
        self.assertIsNone(self.hit(None, [], 999.0, 99.0))
        self.assertIsNone(self.hit([], None, 999.0, 99.0))

    # ── 6. 實盤接線 ──
    def test_trader_uses_helper_and_logs_price_tiers(self):
        src = TRADER_PATH.read_text(encoding="utf-8")
        self.assertRegex(src, r"keep_wait_tier_hit\(kw_tp_tiers, fired_tiers, px, profit_pct\)")
        self.assertIn("'price' in tier", src)
        self.assertIn("現價", src)


if __name__ == "__main__":
    unittest.main()
