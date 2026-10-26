"""迴歸測試：儀表板「策略」欄（2026-10-26 新增）。

背景：`generate_dashboard.py` 的「持倉一覽」多一欄「策略」，資料來源是
`PC_<代號>` 的 `strategy`；`strategy=auto` 會接上 `logs/auto_resolved.json`
鎖定的那一支（`auto→bollinger`），名單上找不到的部位顯示 `-`。

測什麼：
1. `load_portfolio_strategies()` 解析 `PC_` 條目（含 `auto` 接鎖定值）。
2. `build_html()` 真的把「策略」表頭與值放進 HTML。
3. 不在 `PC_` 名單的部位顯示 `-`（不謊報策略）。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pandas as pd

from scripts import generate_dashboard as gd


def _env(**pairs):
    return {f"PC_{k}": json.dumps(v) for k, v in pairs.items()}


class LoadPortfolioStrategiesTest(unittest.TestCase):
    def test_reads_pc_entries_and_auto_lock(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, cwd)
        Path("logs").mkdir()
        Path("logs/auto_resolved.json").write_text(json.dumps({"1301": "bollinger", "2454": "vwap"}),
                                                  encoding="utf-8")
        env = _env(**{
            "1301": {"strategy": "auto", "alloc": 20},
            "1101": {"strategy": "keep_wait", "alloc": 10},
            "2884": {"strategy": "ma_cross", "alloc": 10},
        })
        with mock.patch.dict(os.environ, env, clear=False):
            got = gd.load_portfolio_strategies()
        self.assertEqual(got["1301"], "auto→bollinger", "auto 應接上已鎖定策略")
        self.assertEqual(got["1101"], "keep_wait")
        self.assertEqual(got["2884"], "ma_cross")

    def test_auto_without_lock_stays_auto(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, cwd)
        with mock.patch.dict(os.environ, _env(**{"2330": {"strategy": "auto"}}), clear=False):
            got = gd.load_portfolio_strategies()
        self.assertEqual(got["2330"], "auto")

    def test_broken_json_is_skipped(self):
        with mock.patch.dict(os.environ, {"PC_9999": "{not json"}, clear=False):
            got = gd.load_portfolio_strategies()
        self.assertNotIn("9999", got)


class StrategyColumnRenderedTest(unittest.TestCase):
    def _build(self, holdings, strategies):
        rows = [
            ("2026-10-01 13:30:00", "1301", 70.0, 1000, "BUY", 1),
            ("2026-10-02 13:30:00", "0050", 180.0, 1000, "BUY", 1),
        ]
        df = pd.DataFrame(rows, columns=["timestamp", "symbol", "price", "quantity", "action", "exclude_daily"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        with mock.patch.object(gd, "load_holdings", return_value=holdings), \
             mock.patch.object(gd, "load_stock_allocation", return_value={}), \
             mock.patch.object(gd, "fetch_current_prices", return_value={}), \
             mock.patch.object(gd, "load_portfolio_strategies", return_value=strategies):
            return gd.build_html(df)

    def test_header_and_values_present(self):
        html = self._build({"1301": 1000, "0050": 1000}, {"1301": "auto→bollinger"})
        self.assertIn("<th>策略</th>", html)
        self.assertIn("auto→bollinger", html)
        # 0050 不在 PC_ 名單 → 顯示「-」，不要瞎猜策略
        self.assertIn("<td>0050</td><td>-</td>", html)

    def test_keep_wait_position_shows_keep_wait(self):
        html = self._build({"1301": 1000}, {"1301": "keep_wait"})
        self.assertIn("keep_wait", html)


if __name__ == "__main__":
    unittest.main()
