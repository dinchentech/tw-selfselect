"""迴歸測試：`core/selfselect_scheduler.py` —— 自選股腿的每月自動選股（V4.35）。

使用者規格（2026-09-23）：
  1. 每月**第 1 個交易日**選股、**第 2 個交易日**執行；
  2. 對選股有意見 ⇒ **第 2 個交易日前**可改 `.env`；
  3. 隨時可手動 `VM_pick`／`VM_sync_env`。

本模組只負責「該不該跑、跑什麼、結果怎麼記」；選股與 `.env` 變更一律交給已驗證的
`scripts/monthly_selfselect_run.py`（故容器內不必重寫交易邏輯）。
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import selfselect_scheduler as ss   # noqa: E402

# 2026-10：10/1（四）＝D1、10/2（五）＝D2（10/9 國慶、10/10 補假）
D1 = datetime(2026, 10, 1, 13, 40)
D2 = datetime(2026, 10, 2, 8, 10)


class _R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


class TestWindow(unittest.TestCase):
    def test_d1_window_after_close(self):
        self.assertEqual(ss.pick_window_reason(D1), "D1")
        self.assertEqual(ss.pick_window_reason(datetime(2026, 10, 1, 13, 36)), "D1")
        self.assertEqual(ss.pick_window_reason(datetime(2026, 10, 1, 13, 55)), "D1")


    def test_d1_window_not_before_close(self):
        """選股要用當天收盤資料 ⇒ 13:30 收盤前不可跑。"""
        for hm in ((9, 0), (13, 25), (13, 30)):
            self.assertIsNone(ss.pick_window_reason(datetime(2026, 10, 1, *hm)))

    def test_d2_catchup_before_hot_reload(self):
        """D2 補跑必須在 08:40 熱重載之前，否則新 .env 要等到 D3 才生效。"""
        self.assertEqual(ss.pick_window_reason(D2), "D2_補跑")
        self.assertEqual(ss.pick_window_reason(datetime(2026, 10, 2, 8, 5)), "D2_補跑")
        self.assertIsNone(ss.pick_window_reason(datetime(2026, 10, 2, 8, 40)))
        self.assertIsNone(ss.pick_window_reason(datetime(2026, 10, 2, 8, 41)))

    def test_other_days_are_not_pick_days(self):
        # 10/5（一）既不是 D1 也不是 D2
        self.assertIsNone(ss.pick_window_reason(datetime(2026, 10, 5, 13, 40)))
        # 週末
        self.assertIsNone(ss.pick_window_reason(datetime(2026, 10, 3, 13, 40)))

    def test_month_with_weekend_first_day(self):
        """2026-11：11/1 是週日 ⇒ D1=11/2、D2=11/3。"""
        self.assertEqual(ss.pick_window_reason(datetime(2026, 11, 2, 13, 40)), "D1")
        self.assertIsNone(ss.pick_window_reason(datetime(2026, 11, 1, 13, 40)))
        self.assertEqual(ss.first_trading_day(datetime(2026, 11, 2)).isoformat(), "2026-11-02")
        self.assertEqual(ss.second_trading_day(datetime(2026, 11, 2)).isoformat(), "2026-11-03")


class TestShouldPick(unittest.TestCase):
    def test_runs_once_per_month(self):
        self.assertIsNotNone(ss.should_pick(D1, {}))
        self.assertIsNone(ss.should_pick(D1, {"month": "2026-10", "status": "applied"}))
        # 下個月（11 月）又是新的一輪
        self.assertIsNotNone(ss.should_pick(datetime(2026, 11, 2, 13, 40),
                                            {"month": "2026-10", "status": "applied"}))

    def test_failed_d1_can_be_retried_on_d2(self):
        state = {"month": "2026-10", "status": "failed",
                 "last_attempt_date": "2026-10-01", "attempts": 1}
        due = ss.should_pick(D2, state)
        self.assertIsNotNone(due)
        self.assertEqual(due["day"], "D2_補跑")

    def test_gives_up_after_max_attempts_per_day(self):
        state = {"month": "2026-10", "status": "failed",
                 "last_attempt_date": "2026-10-01", "attempts": ss.MAX_ATTEMPTS}
        self.assertIsNone(ss.should_pick(D1, state), "同一天不要無限重試")

    def test_d1_failure_then_d2_new_day_gets_fresh_attempts(self):
        state = {"month": "2026-10", "status": "failed",
                 "last_attempt_date": "2026-10-01", "attempts": ss.MAX_ATTEMPTS}
        self.assertIsNotNone(ss.should_pick(D2, state), "換一天應該有新的重試額度")


class TestCommandAndParsing(unittest.TestCase):
    def test_command_is_the_tested_sop_script_with_apply(self):
        cmd = ss.picker_command()
        self.assertIn("scripts/monthly_selfselect_run.py", cmd[1])
        self.assertIn("--apply", cmd, "自動選股要真的寫 .env（腳本自己會先備份）")
        self.assertIn("--no-sync", cmd, "容器內持股就是實盤持股，不需要去 VM 抓")
        self.assertIn("--top-n", cmd)

    def test_command_respects_env_overrides(self):
        import os
        os.environ["SELFSELECT_TOP_N"] = "5"
        os.environ["SELFSELECT_RISK"] = "normal"
        try:
            cmd = ss.picker_command()
            self.assertIn("normal", cmd)
            self.assertIn("5", cmd)
        finally:
            os.environ.pop("SELFSELECT_TOP_N", None)
            os.environ.pop("SELFSELECT_RISK", None)

    def test_parse_pick_output(self):
        out = ("選股結果（2026-10-01 00:00:00／正常／N=5）\n"
               "  本月選出：6505, 2884, 2890\n"
               "新增 2 檔 ['6505', '2890']｜保留已持倉 2 檔 ['2006', '3515']｜汰換 1 檔 ['5876']\n"
               "✅ 已寫入 .env（備份：backups/.env.bak-selfselect-20261001-134000）\n")
        info = ss.parse_pick_output(out)
        self.assertEqual(info["picks"], ["6505", "2884", "2890"])
        self.assertIn("新增 2 檔", info["summary"])
        self.assertTrue(info["wrote"])

    def test_parse_detects_stale_and_refusal(self):
        out = ("⚠️  選股基準日 2026-09-30 落後預期的 2026-10-01 ⇒ 這次選股用的是**過期資料**\n"
               "❌ 拒絕寫入 .env：選股基準日 2026-09-30 落後預期的 2026-10-01\n")
        info = ss.parse_pick_output(out)
        self.assertTrue(info["stale"])
        self.assertTrue(info["refused"])


class TestRunIfDue(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = str(Path(self._tmp.name) / "state.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_does_nothing_outside_window(self):
        calls = []
        res = ss.run_if_due(now=datetime(2026, 10, 5, 13, 40), state_path=self.state,
                            runner=lambda *a, **k: calls.append(a), notify=lambda m: calls.append(m))
        self.assertFalse(res["ran"])
        self.assertEqual(calls, [])
        self.assertFalse(Path(self.state).exists())

    def test_success_writes_state_and_notifies_once(self):
        outs = []

        def fake(cmd, **kw):
            outs.append(cmd)
            return _R(0, "  本月選出：6505, 2884\n新增 1 檔 ['6505']｜保留已持倉 2 檔 ['2006', '3515']\n"
                         "✅ 已寫入 .env（備份：x）\n")

        notes = []
        res = ss.run_if_due(now=D1, state_path=self.state, runner=fake, notify=notes.append)
        self.assertTrue(res["ran"] and res["ok"])
        self.assertEqual(res["picks"], ["6505", "2884"])
        self.assertEqual(len(notes), 1)
        self.assertIn("自選股自動選股完成", notes[0])
        self.assertIn("13:25", notes[0], "通知要提醒人工覆寫期限")
        st = json.loads(Path(self.state).read_text(encoding="utf-8"))
        self.assertEqual(st["status"], "applied")
        self.assertEqual(st["month"], "2026-10")

        # 同一個月再呼叫 ⇒ 不重跑、不再通知
        res2 = ss.run_if_due(now=datetime(2026, 10, 1, 13, 50), state_path=self.state,
                             runner=fake, notify=notes.append)
        self.assertFalse(res2["ran"])
        self.assertEqual(len(outs), 1)
        self.assertEqual(len(notes), 1)

    def test_failure_marks_failed_and_notifies_warning(self):
        notes = []
        res = ss.run_if_due(now=D1, state_path=self.state,
                            runner=lambda c, **k: _R(1, "", "❌ 拒絕寫入 .env：…"),
                            notify=notes.append)
        self.assertTrue(res["ran"])
        self.assertFalse(res["ok"])
        st = json.loads(Path(self.state).read_text(encoding="utf-8"))
        self.assertEqual(st["status"], "failed")
        self.assertIn("未被修改", notes[0], "失敗通知要明確說 .env 沒被改")

    def test_timeout_is_a_failure_not_a_crash(self):
        def boom(cmd, **kw):
            raise TimeoutError("900s 逾時")

        notes = []
        res = ss.run_if_due(now=D1, state_path=self.state, runner=boom, notify=notes.append)
        self.assertFalse(res["ok"])
        self.assertEqual(json.loads(Path(self.state).read_text(encoding="utf-8"))["status"], "failed")

    def test_corrupt_state_file_is_tolerated(self):
        Path(self.state).write_text("{not json", encoding="utf-8")
        res = ss.run_if_due(now=D1, state_path=self.state,
                            runner=lambda c, **k: _R(0, "本月選出：2884\n✅ 已寫入 .env（備份：x）\n"),
                            notify=None)
        self.assertTrue(res["ran"] and res["ok"])


class TestTraderWiring(unittest.TestCase):
    def setUp(self):
        self.src = (ROOT / "selfselect_trader.py").read_text(encoding="utf-8")

    def test_disabled_by_default(self):
        for name, src in (("main", self.src),):
            self.assertIn("os.getenv('SELFSELECT_AUTO', '0') == '1'", src,
                          f"{name}: 自動選股必須預設關閉（deploy 後由使用者在 .env 打開）")

    def test_trigger_present_and_isolated(self):
        for name, src in (("main", self.src),):
            self.assertIn("from core.selfselect_scheduler import run_if_due", src, name)
            self.assertIn("_hot_reload_date'] = None", src, f"{name}: 補跑後要強制熱重載")
            # 例外不可影響其他策略
            self.assertIn("自選股自動選股異常（不影響其他策略）", src, name)




if __name__ == "__main__":
    unittest.main(verbosity=2)
