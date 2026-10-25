"""迴歸測試：熱新增標的（改 `.env` 名單 → 熱重載）不可讓分帳本 KeyError。

事故（2026-10-01 實盤，真錢）：
  B 腿補考時把 `PC_2409`／`PC_6505`／`PC_3443` 寫進 VM 的 `.env` ⇒ 熱重載把三個代號加進
  `PORTFOLIO_CONFIG`、也初始化了 `portfolio_history`，**但沒有同步初始化分帳本
  `stock_alloc`（`logs/stock_allocation.json` 是啟動時載入的快照）**。
  三筆單**都成交了**（2409×3000、6505×1000、3443×12），卻在買進後的記帳那行炸掉：

      stock_alloc[symbol]['total_buy_cost'] += trade_cost     # KeyError('2409')

  後果：① 分帳本缺這三檔（資金利用率/分帳統計不準）；② 該圈在 `send_trade_alert` 之前中斷
  ⇒ 使用者沒收到成交通知，反而收到 `notify_order_failure` 的「⚠️ *2409* 買入失敗：'2409'」
  **誤導性告警**（一檔一則）。

注意：`load_stock_allocation()` 在**啟動時**本來就會對 `PORTFOLIO_CONFIG` 做 `setdefault`
（selfselect_trader.py 內的同名閉包），所以只有「執行期熱新增」這條路會漏 —— 這正是本測試要釘住的。
"""
import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.live_state import ensure_symbol_ledgers  # noqa: E402

SRC = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")


class TestEnsureSymbolLedgers(unittest.TestCase):
    DEFAULT = {"total_buy_cost": 0, "total_buy_shares": 0}

    def test_creates_missing_symbols(self):
        alloc = {"3017": {"total_buy_cost": 315080.4, "total_buy_shares": 92}}
        ensure_symbol_ledgers(alloc, ["3017", "2409", "6505"])
        self.assertEqual(alloc["2409"], self.DEFAULT)
        self.assertEqual(alloc["6505"], self.DEFAULT)

    def test_preserves_existing_values(self):
        alloc = {"3017": {"total_buy_cost": 315080.4, "total_buy_shares": 92}}
        ensure_symbol_ledgers(alloc, ["3017"])
        self.assertEqual(alloc["3017"]["total_buy_shares"], 92)
        self.assertEqual(alloc["3017"]["total_buy_cost"], 315080.4)

    def test_repairs_half_broken_entry(self):
        """條目存在但缺欄位（舊 schema／手改壞）也要補齊，否則 += 一樣會炸。"""
        alloc = {"2409": {"total_buy_cost": 100.0}}
        ensure_symbol_ledgers(alloc, ["2409"])
        self.assertEqual(alloc["2409"]["total_buy_shares"], 0)
        self.assertEqual(alloc["2409"]["total_buy_cost"], 100.0)

    def test_idempotent_and_returns_alloc(self):
        alloc = {}
        first = ensure_symbol_ledgers(alloc, ["2409"])
        second = ensure_symbol_ledgers(first, ["2409"])
        self.assertIs(first, alloc)
        self.assertEqual(second, {"2409": self.DEFAULT})

    def test_serialisable_after_repair(self):
        alloc = {}
        ensure_symbol_ledgers(alloc, ["3443"])
        self.assertIn("3443", json.loads(json.dumps(alloc)))


class TestHotReloadWiresIt(unittest.TestCase):
    def test_reload_env_config_initialises_ledgers(self):
        """`_reload_env_config` 必須替新代號初始化分帳本（否則回到 2026-10-01 的事故）。"""
        tree = ast.parse(SRC)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_reload_env_config"), None)
        self.assertIsNotNone(fn, "找不到 _reload_env_config")
        called = [n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertIn("ensure_symbol_ledgers", called,
                      "_reload_env_config 必須呼叫 ensure_symbol_ledgers 同步分帳本")

    def test_no_raw_ledger_indexing(self):
        """買進記帳不得再用 `stock_alloc[symbol]['...'] +=`（KeyError 的來源）。"""
        for lineno, line in enumerate(SRC.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            self.assertNotIn("stock_alloc[symbol][", line,
                             f"selfselect_trader.py:{lineno} 仍在直接索引分帳本，改用 ensure_symbol_ledgers")


if __name__ == "__main__":
    unittest.main()
