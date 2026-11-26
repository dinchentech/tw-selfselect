#!/usr/bin/env python
"""回歸測試：`reset_paper_trading` 的清空清單必須涵蓋停泊與待對帳（2026-11-26，v1.1.54）。

事故：執行「從零重來」後 `park_position.json` 仍留著 9,000 股（成本 825,575）
⇒ 帳面總成本（持股 617,555 ＋ 停泊 825,575）仍超過本金，現金永遠是 0。
"""
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.reset_paper_trading import STATE_FILES  # noqa: E402


class TestResetCoversParking(unittest.TestCase):

    def test_parking_state_is_cleared(self):
        for f in ("park_position.json", "park_trades.jsonl", "park_plan.json",
                  "stock_pending.json", "entry_attempts.json"):
            self.assertIn(f, STATE_FILES, f"{f} 必須在重置清單裡（否則重置後帳面仍超過本金）")

    def test_core_books_still_cleared(self):
        for f in ("holdings.json", "stock_allocation.json", "performance.csv"):
            self.assertIn(f, STATE_FILES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
