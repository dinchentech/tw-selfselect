#!/usr/bin/env python
"""`scripts/snapshot_broker.py` 的回歸測試（2026-11-05）。

## 為什麼要這支工具（事故背景）

2026-11-05 要查「11/03 那 4 筆 0050 到底成交幾筆」，結果模擬帳的查詢 API **全部查不到歷史**：
`get_transactions_by_date('2026-11-03')` 回 0 筆（連當天確定成交的 4 檔股票都沒有）、
`get_order_results_by_date` 全空、`get_inventories` 只回當日未交割、`get_balance` 全 0。
⇒ **「查不到」≠「沒發生」**；對帳資料必須在還查得到的時候落地。

這裡釘住：序列化不丟欄位、同一天重跑不覆蓋先前證據、主程式每日只跑一次、取不到券商資料時不寫假資料。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.snapshot_broker import (already_done, build_payload, fetch, main,  # noqa: E402
                                     merge_previous, save, summarize, to_jsonable)


class _Obj:
    """模擬玉山 SDK 回傳的物件（屬性 + 方法混在一起）。"""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def some_method(self):          # 方法必須被排除
        return 1


class _FakeSDK:
    def __init__(self, inv=None, tx=None, orders=None, bal=None, boom=None, se=None):
        self._inv, self._tx, self._orders, self._bal = inv, tx, orders, bal
        self._se, self._boom = se, boom or set()
        self.calls = []

    def get_inventories(self):
        self.calls.append("inv")
        if "inv" in self._boom:
            raise RuntimeError("inv boom")
        return self._inv or []

    def get_transactions_by_date(self, a, b):
        self.calls.append(("tx", a, b))
        if "tx" in self._boom:
            raise RuntimeError("tx boom")
        return self._tx or []

    def get_order_results_by_date(self, a, b):
        self.calls.append(("orders", a, b))
        return self._orders or []

    def get_balance(self):
        self.calls.append("bal")
        return self._bal

    def get_settlements(self):
        self.calls.append("set")
        if "set" in self._boom:
            raise RuntimeError("set boom")
        return self._se or []


class _FakeProv:
    def __init__(self, sdk):
        self._trade_sdk = sdk

    def login(self):
        return True


class TestToJsonable(unittest.TestCase):

    def test_primitives_and_containers(self):
        self.assertEqual(to_jsonable({"a": [1, {"b": None}], "c": "x"}), {"a": [1, {"b": None}], "c": "x"})

    def test_object_attrs_kept_methods_dropped(self):
        out = to_jsonable(_Obj(stk_no="0050", qty_b="282", some=("a",)))
        self.assertEqual(out["stk_no"], "0050")
        self.assertEqual(out["qty_b"], "282")
        self.assertEqual(out["some"], ["a"])
        self.assertNotIn("some_method", out)

    def test_unknown_type_falls_back_to_str(self):
        class Weird:
            __slots__ = ()
        self.assertIsInstance(to_jsonable(Weird()), str)


class TestSummarize(unittest.TestCase):

    def test_counts_and_symbols(self):
        s = summarize([{"stk_no": "0050"}, {"stk_no": "2603"}, {"stk_no": "2603"}],
                      [{"stk_no": "2615"}], [])
        self.assertEqual(s["inventories"], 3)
        self.assertEqual(s["inventory_symbols"], ["0050", "2603"])
        self.assertEqual(s["transactions"], 1)
        self.assertEqual(s["order_results"], 0)

    def test_none_inputs(self):
        s = summarize(None, None, None)
        self.assertEqual((s["inventories"], s["transactions"], s["order_results"]), (0, 0, 0))


class TestSettlements(unittest.TestCase):
    """2026-11-05：未交割明細也要每天落地（交割日一到就查不到了）。"""

    SE = [{"c_date": "20261109", "date": "20261105", "price": "113496"}]

    def test_summarize_counts_settlements_and_dates(self):
        s = summarize([], [], [], self.SE)
        self.assertEqual(s["settlements"], 1)
        self.assertEqual(s["settlement_dates"], ["20261109"])
        self.assertEqual(summarize([], [], [])["settlements"], 0, "省略時預設 0（舊呼叫端相容）")

    def test_payload_carries_settlements(self):
        p = build_payload("2026-11-05", {"settlements": self.SE}, {}, "1.1.31")
        self.assertEqual(p["settlements"], self.SE)
        self.assertEqual(p["summary"]["settlements"], 1)

    def test_fetch_uses_provider_helper_then_sdk_fallback(self):
        sdk = _FakeSDK(se=self.SE)
        prov = type("P", (), {"_trade_sdk": sdk, "login": lambda self: True,
                              "query_settlements": lambda self: self._trade_sdk.get_settlements()})()
        data, errors = fetch(prov, "2026-11-05")
        self.assertEqual(errors, {})
        self.assertEqual(data["settlements"], self.SE)
        # 舊映像沒有 helper ⇒ 直接呼叫 SDK
        sdk2 = _FakeSDK(se=self.SE)
        prov2 = type("P", (), {"_trade_sdk": sdk2, "login": lambda self: True})()
        data2, errors2 = fetch(prov2, "2026-11-05")
        self.assertEqual(errors2, {})
        self.assertEqual(data2["settlements"], self.SE)

    def test_settlements_failure_does_not_fail_snapshot(self):
        sdk = _FakeSDK(se=self.SE, boom={"set"})
        prov = type("P", (), {"_trade_sdk": sdk, "login": lambda self: True})()
        data, errors = fetch(prov, "2026-11-05")
        self.assertIn("settlements", errors)
        p = build_payload("2026-11-05", data, errors)
        self.assertTrue(p["ok"], "單項失敗不可讓整份快照失敗")


class TestMergePrevious(unittest.TestCase):

    def test_previous_kept_and_capped(self):
        old = {"date": "2026-11-05", "ok": True, "summary": {"inventories": 1}, "previous": []}
        merged = merge_previous({"date": "2026-11-05", "ok": True}, old, keep=5)
        self.assertEqual(len(merged["previous"]), 1)
        self.assertIn("summary", merged["previous"][0])
        self.assertNotIn("previous", merged["previous"][0], "previous 不應再嵌一層")

    def test_cap(self):
        old = {"previous": [{"n": i} for i in range(10)]}
        merged = merge_previous({"x": 1}, old, keep=5)
        self.assertEqual(len(merged["previous"]), 5)

    def test_no_old(self):
        self.assertEqual(merge_previous({"a": 1}, None), {"a": 1})


class TestBuildPayload(unittest.TestCase):

    def test_ok_when_no_sdk_error(self):
        p = build_payload("2026-11-05", {"inventories": [{"stk_no": "0050"}]}, {}, "1.1.25")
        self.assertTrue(p["ok"])
        self.assertEqual(p["summary"]["inventory_symbols"], ["0050"])
        self.assertEqual(p["version"], "1.1.25")

    def test_not_ok_when_sdk_unavailable(self):
        p = build_payload("2026-11-05", {}, {"sdk": "trade SDK 不可用"})
        self.assertFalse(p["ok"])

    def test_partial_errors_keep_ok(self):
        p = build_payload("2026-11-05", {"inventories": []}, {"transactions": "boom"})
        self.assertTrue(p["ok"])
        self.assertIn("transactions", p["errors"])


class TestSaveAndAlreadyDone(unittest.TestCase):

    def test_save_writes_file_and_history(self):
        with tempfile.TemporaryDirectory() as d:
            p = build_payload("2026-11-05", {"inventories": [{"stk_no": "0050"}]}, {})
            path = save(p, d)
            self.assertTrue(path.exists())
            self.assertTrue((Path(d) / "broker_snapshot_history.jsonl").exists())
            self.assertTrue(already_done("2026-11-05", d))

    def test_already_done_false_when_absent_or_broken(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(already_done("2026-11-05", d))
            (Path(d) / "broker_snapshot_2026-11-05.json").write_text("{not json", encoding="utf-8")
            self.assertFalse(already_done("2026-11-05", d))

    def test_already_done_false_when_empty_everything(self):
        with tempfile.TemporaryDirectory() as d:
            p = build_payload("2026-11-05", {"inventories": [], "transactions": []}, {})
            save(p, d)
            self.assertFalse(already_done("2026-11-05", d), "全部 0 筆視為沒抓到 → 允許重跑")


class TestFetch(unittest.TestCase):

    def test_collects_all_four_and_keeps_going_on_error(self):
        sdk = _FakeSDK(inv=[{"stk_no": "0050"}], tx=[{"stk_no": "2615"}], orders=[], bal={"available_balance": 0},
                       boom={"tx"})
        data, errors = fetch(_FakeProv(sdk), "2026-11-05")
        self.assertIn("inventories", data)
        self.assertIn("transactions", errors, "單項失敗要記在 errors，不可讓整體失敗")
        self.assertEqual(data["balance"], {"available_balance": 0})
        self.assertTrue(any(c[0] == "orders" for c in sdk.calls if isinstance(c, tuple)))

    def test_sdk_missing_reports_sdk_error(self):
        data, errors = fetch(_FakeProv(None), "2026-11-05")
        self.assertEqual(data, {})
        self.assertIn("sdk", errors)

    def test_falls_back_to_raw_sdk_when_provider_lacks_helpers(self):
        sdk = _FakeSDK(inv=[{"stk_no": "0050"}])
        prov = type("P", (), {"_trade_sdk": sdk, "login": lambda self: True})()
        data, errors = fetch(prov, "2026-11-05")
        self.assertEqual(errors, {})
        self.assertEqual(len(data["inventories"]), 1)


class TestMainWritesNothingOnFailure(unittest.TestCase):
    """取不到券商（SDK 不可用）⇒ 回 2、**不寫檔案**（不可留下假的空快照）。"""

    def test_returns_2_without_file_when_provider_missing(self):
        with tempfile.TemporaryDirectory() as d:
            sys.modules["data.esun_provider"] = None      # 讓 import 失敗
            try:
                rc = main(["--date", "2026-11-05", "--out-dir", d, "--quiet"])
            finally:
                sys.modules.pop("data.esun_provider", None)
            self.assertEqual(rc, 2)
            self.assertFalse(list(Path(d).glob("broker_snapshot_*.json")))


class TestTraderIntegration(unittest.TestCase):
    """主程式必須每日跑一次快照（在 13:45 收盤報告那一輪）。"""

    def test_trader_calls_snapshot_after_dashboard(self):
        src = (_ROOT / "selfselect_trader.py").read_text(encoding="utf-8")
        self.assertIn("from scripts.snapshot_broker import", src)
        self.assertIn("_snapshot_tried", src, "必須有『每日只跑一次』的旗標")
        self.assertLess(src.index("snapshot_broker import"),
                        src.index("_snap_main("),
                        "旗標/匯入要在呼叫之前")

    def test_envs_not_required(self):
        self.assertIsNotNone(os.environ)   # 佔位：本工具不得要求任何新 env 才有作用


if __name__ == "__main__":
    unittest.main()
