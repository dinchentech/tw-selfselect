"""迴歸測試：`scripts/monthly_selfselect_run.py`（把自選股 SOP 步驟 1–4 合成一支程式）。

SOP 1–4 原本是：①跑 picker（抓回實盤 holdings）②讀 賣出/維持/買入 ③改本機 `.env` 的 `PC_` 區段
④同步到 VM。本工具把它們合成一步，但**保留人為關卡**：
  - 預設 **dry-run**（只印 diff，不寫檔）；要真的寫入必須加 `--apply`。
  - **絕不刪除「已持倉」的股票**（刪了會被孤兒清倉賣掉）——這是硬性安全檢查。
  - **絕不動 keep_wait（另一條腿）**。
  - 只 scp `.env`；程式改動仍要人工 `deploy_source.sh`（部署硬規則）。
"""
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "_msr", ROOT / "scripts" / "monthly_selfselect_run.py")
msr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(msr)

ENV = """# header
PC_3017={"strategy":"keep_wait","alloc":26.7,"max_entry_price":-1,"initial_buy_pct":1.0}
PC_3653={"strategy":"keep_wait","alloc":16.7,"max_entry_price":-1,"initial_buy_pct":1.0}
# === 非輪替（自選股）
PC_2006={"strategy":"auto","alloc":6.0,"max_entry_price":84.8}
PC_3515={"strategy":"auto","alloc":6.0,"max_entry_price":235.5}
PC_2884={"strategy":"auto","alloc":6.0,"max_entry_price":46.26}
PC_2881={"strategy":"auto","alloc":6.0,"max_entry_price":153.0}
PC_5876={"strategy":"auto","alloc":6.0,"max_entry_price":49.75}
PC_9999={"strategy":"auto","alloc":5.0,"max_entry_price":10.0}
TOTAL_CAPITAL=1200000
"""


class TestPoolNWiring(unittest.TestCase):
    """2026-10-27：候選池大小 `--pool-n`（SELFSELECT_POOL_N）接線。"""

    def test_resolve_pool_n(self):
        # 2026-10-30 起預設 preset 是 aggressive ⇒ 未設定時池為 150（先前為 100）
        self.assertEqual(msr.resolve_pool_n(None, {}), 150, "未設定時採用預設 preset aggressive 的池")
        self.assertEqual(msr.resolve_pool_n(None, {"SELFSELECT_PRESET": "revenue"}), 100)
        self.assertEqual(msr.resolve_pool_n(None, {"SELFSELECT_PRESET": "current"}), 100)
        self.assertEqual(msr.resolve_pool_n(None, {"SELFSELECT_POOL_N": "50"}), 50)
        self.assertEqual(msr.resolve_pool_n(30, {"SELFSELECT_POOL_N": "50"}), 30, "CLI 優先")
        self.assertEqual(msr.resolve_pool_n(None, {"SELFSELECT_POOL_N": "oops"}), 150)
        self.assertEqual(msr.resolve_pool_n(None, {"SELFSELECT_POOL_N": "0"}), 150)

    def test_picker_cmd_includes_pool_n(self):
        import argparse
        args = argparse.Namespace(risk="normal", top_n=5, sync_holdings_from_vm=False,
                                  vm=None, zone=None, allow_stale_holdings=False,
                                  ignore_drawback=False)
        cmd = msr.build_picker_cmd(args, 50)
        self.assertEqual(cmd[cmd.index("--pool-n") + 1], "50")
        self.assertEqual(cmd[cmd.index("--top-n") + 1], "5")
        self.assertNotIn("--sync-holdings-from-vm", cmd)
        self.assertNotIn("--allow-stale-holdings", cmd)

    def test_picker_cmd_carries_flags(self):
        import argparse
        args = argparse.Namespace(risk="high_profit", top_n=3, sync_holdings_from_vm=True,
                                  vm="my-vm", zone="asia-east1-b", allow_stale_holdings=True,
                                  ignore_drawback=True)
        cmd = msr.build_picker_cmd(args, 100)
        self.assertIn("--sync-holdings-from-vm", cmd)
        self.assertEqual(cmd[cmd.index("--vm") + 1], "my-vm")
        self.assertIn("--allow-stale-holdings", cmd)
        self.assertIn("--ignore-drawback", cmd)
        self.assertEqual(cmd[cmd.index("--risk") + 1], "high_profit")


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.held = {"2006": 689, "3515": 286, "3017": 94, "3653": 34}
        self.selected = ["2884", "2881", "5876"]      # 本月選出（新名）
        self.cfg = msr.parse_pc_lines(ENV)

    def test_removes_only_flat_unselected(self):
        plan = msr.plan_env_changes(ENV, self.held, self.selected, per_name_alloc=6.0)
        self.assertEqual(plan["remove"], ["9999"], "0 股且未選中者才可移除")
        self.assertEqual(plan["add"], [])
        self.assertEqual(sorted(plan["keep_held"]), ["2006", "3515"])

    def test_never_removes_held_even_if_unselected(self):
        plan = msr.plan_env_changes(ENV, self.held, ["2884"], per_name_alloc=6.0)
        self.assertNotIn("2006", plan["remove"])
        self.assertNotIn("3515", plan["remove"])
        self.assertNotIn("3017", plan["remove"], "keep_wait 屬另一條腿，不可動")

    def test_adds_new_selected_with_alloc(self):
        plan = msr.plan_env_changes(ENV, self.held, ["2884", "2881", "5876", "3045"],
                                    per_name_alloc=6.0, prices={"3045": 124.0})
        self.assertEqual(plan["add"], ["3045"])
        # 新條目要帶 strategy/alloc（價位有提供時一併寫入 max_entry_price）
        self.assertIn('"strategy":"auto"', plan["env_text"].split("PC_3045=")[1].split("\n")[0])
        self.assertIn('"alloc":6.0', plan["env_text"].split("PC_3045=")[1].split("\n")[0])
        self.assertIn('"max_entry_price":124.0', plan["env_text"].split("PC_3045=")[1].split("\n")[0])

    def test_keep_wait_lines_untouched(self):
        plan = msr.plan_env_changes(ENV, self.held, ["2884"], per_name_alloc=6.0)
        self.assertIn('PC_3017={"strategy":"keep_wait","alloc":26.7,"max_entry_price":-1,'
                      '"initial_buy_pct":1.0}', plan["env_text"])
        self.assertIn('PC_3653={"strategy":"keep_wait","alloc":16.7,"max_entry_price":-1,'
                      '"initial_buy_pct":1.0}', plan["env_text"])

    def test_aborts_if_a_held_name_would_be_removed(self):
        """模擬 bug：held 判斷錯時，計畫想把持股刪掉 → 必須拒絕產生計畫。"""
        with self.assertRaises(msr.SafetyError):
            msr.plan_env_changes(ENV, {"2006": 689}, ["2884"], per_name_alloc=6.0,
                                 force_remove=["2006"])

    def test_warns_when_total_alloc_over_100(self):
        plan = msr.plan_env_changes(ENV, self.held, ["2884", "2881", "5876", "3045", "6505"],
                                    per_name_alloc=20.0)
        self.assertTrue(plan["warnings"], "Σalloc 超過 100% 應該要警告")
        self.assertTrue(any("100" in w for w in plan["warnings"]))

    def test_summary_reports_leg_budget_and_new_buy_amount(self):
        plan = msr.plan_env_changes(ENV, self.held, ["2884", "2881", "5876", "3045"],
                                    per_name_alloc=6.0, total_capital=1_200_000)
        self.assertEqual(plan["new_buy_amount"], 72_000)     # 1 檔 × 6% × 120 萬
        self.assertIn("腿額度", plan["summary"])

    def test_new_lines_inserted_next_to_existing_leg_entries(self):
        """新條目要插在現有自選股條目旁邊（不是檔尾），避免被塞進別的區段。"""
        plan = msr.plan_env_changes(ENV, self.held, ["2884", "2881", "5876", "3045"],
                                    per_name_alloc=6.0, prices={"3045": 124.0})
        lines = plan["env_text"].split("\n")
        i_new = next(i for i, l in enumerate(lines) if l.startswith("PC_3045="))
        i_prev = next(i for i, l in enumerate(lines) if l.startswith("PC_5876="))
        i_other = next(i for i, l in enumerate(lines) if l.startswith("TOTAL_CAPITAL="))
        self.assertEqual(i_new, i_prev + 1, "新條目應緊接在既有自選股條目之後")
        self.assertLess(i_new, i_other, "不可被塞到檔案最後的其他設定區")

    def test_realloc_resets_all_leg_entries(self):
        plan = msr.plan_env_changes(ENV, self.held, ["2884"], per_name_alloc=4.0, realloc=True)
        self.assertIn('PC_2006={"strategy":"auto","alloc":4.0', plan["env_text"])
        self.assertIn('PC_3515={"strategy":"auto","alloc":4.0', plan["env_text"])
        # keep_wait 不受影響
        self.assertIn('"alloc":26.7', plan["env_text"])

    def test_realloc_keeps_line_comments(self):
        env = ('PC_2006={"strategy":"auto","alloc":6.0,"max_entry_price":84.8}   '
               '# 已持倉：保留到賣訊（不可移除）\n')
        plan = msr.plan_env_changes(env, {"2006": 689}, ["2006"], per_name_alloc=4.0, realloc=True)
        self.assertIn("不可移除", plan["env_text"], "改 alloc 不該把行尾註解吃掉")
        self.assertIn('"alloc":4.0', plan["env_text"])


class TestCliSafety(unittest.TestCase):
    def test_apply_is_opt_in(self):
        src = (ROOT / "scripts" / "monthly_selfselect_run.py").read_text(encoding="utf-8")
        self.assertIn("--apply", src)
        self.assertIn("dry-run", src.lower())
        # 不得內建呼叫 deploy 腳本（部署是人工硬規則）
        self.assertNotIn("deploy.sh", src)
        self.assertNotIn("deploy_source.sh\", ", src)

    def test_manual_documents_one_command(self):
        manual = (ROOT / "使用手冊.md").read_text(encoding="utf-8")
        self.assertIn("monthly_selfselect_run.py", manual)


class TestManualEditVsReplan(unittest.TestCase):
    """V4.33：文件說「手改 .env 名單會被重跑的計畫覆蓋」——這裡把該行為釘住。

    起因：使用者問「VM_pick 之後想改選股結果，是不是 VM_wr_env → 手改 .env → VM_sync_env？」
    答案是否定的：`VM_sync_env` = `--apply --sync-env-to-vm` **會重跑選股並重算計畫**，
    所以「刪掉被選中的股」會被加回來、「手動新增非選中股」會被當汰換刪掉。
    """
    HELD = {"2006": 689, "3515": 286}
    SEL = ["2884", "2881", "5876"]

    def _base(self):
        return ('PC_2006={"strategy":"auto","alloc":6.0}\n'
                'PC_2884={"strategy":"auto","alloc":6.0}\n'
                'PC_2881={"strategy":"auto","alloc":6.0}\n'
                'PC_5876={"strategy":"auto","alloc":6.0}\nTOTAL_CAPITAL=1200000\n')

    def test_manual_line_deletion_is_undone_by_replan(self):
        edited = "\n".join(l for l in self._base().split("\n") if "PC_2884" not in l)
        plan = msr.plan_env_changes(edited, self.HELD, self.SEL, per_name_alloc=6.0)
        self.assertIn("PC_2884", plan["env_text"],
                      "重算計畫會把『被選中但被手動刪掉』的股票加回來 ⇒ 手改名單無效")

    def test_manual_addition_of_unselected_is_treated_as_replace(self):
        edited = self._base() + 'PC_2454={"strategy":"auto","alloc":6.0}\n'
        plan = msr.plan_env_changes(edited, self.HELD, self.SEL, per_name_alloc=6.0)
        self.assertIn("2454", plan["remove"], "手動新增的非選中股會被視為汰換")
        self.assertNotIn("PC_2454", plan["env_text"])

    def test_alloc_edit_survives_replan(self):
        edited = self._base().replace('PC_2884={"strategy":"auto","alloc":6.0}',
                                      'PC_2884={"strategy":"auto","alloc":4.0}')
        plan = msr.plan_env_changes(edited, self.HELD, self.SEL, per_name_alloc=6.0)
        self.assertIn('PC_2884={"strategy":"auto","alloc":4.0}', plan["env_text"],
                      "既有條目的參數（alloc 等）在沒 --realloc 時不該被動到")

    def test_exclude_is_the_supported_way_to_drop_a_pick(self):
        """--exclude 是宣告式剔除：重跑結果穩定（不會被加回來）。"""
        plan = msr.plan_env_changes(self._base(), self.HELD, ["2881", "5876"],
                                    per_name_alloc=6.0)
        self.assertIn("2884", plan["remove"], "剔除且 0 股 ⇒ 汰換")
        self.assertNotIn("PC_2884", plan["env_text"])

    def test_parse_exclude_accepts_comma_and_repeat(self):
        self.assertEqual(msr.parse_exclude(["2884,2881", "5876"]), ["2884", "2881", "5876"])
        self.assertEqual(msr.parse_exclude(["2884", "2884"]), ["2884"], "去重")
        self.assertEqual(msr.parse_exclude(None), [])
        self.assertEqual(msr.parse_exclude([" 2884 , 2881 "]), ["2884", "2881"], "容忍空白")


class TestSyncOnly(unittest.TestCase):
    """`--sync-only`：已手改好本機 .env 時的純上傳路徑（不重算計畫）。"""

    def test_validate_rejects_orphan_held_name(self):
        """手改 .env 最致命的錯誤：把已持倉的股票刪掉 ⇒ 開盤被清倉。"""
        env = 'PC_2006={"strategy":"auto","alloc":6.0}\n'
        problems = msr.validate_env_for_push(env, {"2006": 689, "3515": 286})
        self.assertTrue(problems)
        self.assertIn("3515", " ".join(problems))

    def test_validate_accepts_clean_env(self):
        env = ('PC_2006={"strategy":"auto","alloc":6.0}\n'
               'PC_3515={"strategy":"auto","alloc":6.0}\n')
        self.assertEqual(msr.validate_env_for_push(env, {"2006": 689, "3515": 286}), [])

    def test_validate_rejects_broken_json(self):
        problems = msr.validate_env_for_push('PC_2006={oops\n', {})
        self.assertTrue(any("解析" in p for p in problems))

    def test_validate_rejects_empty_env(self):
        self.assertTrue(msr.validate_env_for_push("# nothing\n", {}))

    def test_sync_only_refuses_combination_with_apply(self):
        src = (ROOT / "scripts" / "monthly_selfselect_run.py").read_text(encoding="utf-8")
        self.assertIn("--sync-only 是『純上傳本機 .env』", src)

    def test_push_helper_verifies_remote_md5(self):
        import tempfile
        calls = []

        class _R:
            def __init__(self, rc=0, out="", err=""):
                self.returncode, self.stdout, self.stderr = rc, out, err

        def fake_runner(cmd, **kw):
            calls.append(cmd)
            if "ssh" in cmd:
                return _R(0, "abc123  /home/x/tw-autotrader/.env\n")
            return _R(0, "")

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('PC_2006={"strategy":"auto","alloc":6.0}\n', encoding="utf-8")
            ok, msg, local, remote = msr.push_env_to_vm(p, runner=fake_runner)
        self.assertTrue(ok, msg)
        self.assertEqual(len(local), 32)
        self.assertEqual(remote, "abc123", "scp 後要回讀 VM 的 md5")
        self.assertIn("scp", calls[0])
        self.assertIn("ssh", calls[1])

    def test_push_helper_reports_scp_failure(self):
        class _R:
            returncode, stdout, stderr = 1, "", "gcloud boom"

        ok, msg, local, remote = msr.push_env_to_vm(
            Path(__file__), runner=lambda cmd, **kw: _R())
        self.assertFalse(ok)
        self.assertIn("boom", msg)
        self.assertIsNone(remote)


class TestStep0Refresh(unittest.TestCase):
    """V4.34 步驟 0：選股前補資料 ＋ 基準日把關。

    起因（實測）：`monthly_rebalance_picker.py` 不會自己補價（`ensure_fresh()` 只在
    `stock_selector_grid.py --recommend` 裡跑）⇒ 2026-09-22 那次跑的基準日是 **09-16**
    （`logs/monthly_pick.json` 的 `as_of`），落後 4 個交易日，等於用舊價格選股。
    """

    TUE_AM = datetime(2026, 9, 22, 11, 0)      # 交易日盤中
    TUE_PM = datetime(2026, 9, 22, 14, 0)      # 交易日盤後
    SAT = datetime(2026, 9, 19, 11, 0)         # 週六
    HOLIDAY_PM = datetime(2026, 9, 25, 14, 0)  # 中秋節（休市）

    def test_intraday_refresh_is_skipped(self):
        """盤中不可補價：會把未定案的當日 K 棒寫進快取（2026-09-17 事故同一類）。"""
        reason = msr.refresh_guard_reason(self.TUE_AM)
        self.assertIsNotNone(reason)
        self.assertIn("盤中", reason)

    def test_after_close_refresh_allowed(self):
        self.assertIsNone(msr.refresh_guard_reason(self.TUE_PM))

    def test_weekend_and_holiday_refresh_allowed(self):
        self.assertIsNone(msr.refresh_guard_reason(self.SAT))
        self.assertIsNone(msr.refresh_guard_reason(self.HOLIDAY_PM))

    def test_expected_data_date_before_close_is_previous_trading_day(self):
        # 9/22（二）盤中 ⇒ 基準日應為 9/21（一）
        self.assertEqual(msr.expected_data_date(self.TUE_AM), "2026-09-21")
        # 9/22 盤後 ⇒ 基準日就是 9/22
        self.assertEqual(msr.expected_data_date(self.TUE_PM), "2026-09-22")

    def test_expected_data_date_skips_holiday(self):
        # 9/25 中秋節休市、9/26-27 週末、9/28 教師節 ⇒ 9/29（二）盤中的前一交易日是 9/24
        self.assertEqual(msr.expected_data_date(datetime(2026, 9, 29, 11, 0)), "2026-09-24")

    def test_refresh_runs_both_scripts_with_apply(self):
        calls = []

        class _R:
            returncode, stdout, stderr = 0, "done", ""

        def fake(cmd, **kw):
            calls.append(cmd)
            return _R()

        rep = msr.refresh_basis_data(runner=fake, now=self.TUE_PM)
        names = [os.path.basename(c[1]) for c in calls]
        self.assertEqual(names, ["rebuild_mcap_ranking.py", "append_selector_prices.py"],
                         "先重建市值排名（決定補價的候選池），再補價")
        self.assertTrue(all("--apply" in c for c in calls), "兩支腳本預設 dry-run，必須帶 --apply")
        self.assertEqual(len(rep["results"]), 2)

    def test_refresh_skipped_intraday_does_not_run_scripts(self):
        calls = []
        rep = msr.refresh_basis_data(runner=lambda c, **k: calls.append(c), now=self.TUE_AM)
        self.assertIn("skipped", rep)
        self.assertEqual(calls, [], "盤中不該執行任何補價腳本")

    def test_refresh_failure_is_not_fatal(self):
        """補價失敗不可阻斷選股（使用手冊 §10.7 既有原則）：回報但不拋例外。"""

        def boom(cmd, **kw):
            raise OSError("no network")

        rep = msr.refresh_basis_data(runner=boom, now=self.TUE_PM)
        self.assertEqual(len(rep["results"]), 2)
        self.assertTrue(all(rc is None for _, rc, _ in rep["results"]))

    def test_warning_when_basis_date_lags(self):
        msg = msr.basis_data_warning("2026-09-16 00:00:00", "2026-09-22", "2026-09-16")
        self.assertIsNotNone(msg)
        self.assertIn("2026-09-16", msg)
        self.assertIn("4 個交易日", msg)      # 9/17,9/18,9/21,9/22
        self.assertIn("價格快取最新只到", msg)

    def test_no_warning_when_basis_date_fresh(self):
        self.assertIsNone(msr.basis_data_warning("2026-09-22 00:00:00", "2026-09-22"))
        self.assertIsNone(msr.basis_data_warning("", "2026-09-22"))
        self.assertIsNone(msr.basis_data_warning("2026-09-23", "2026-09-22"), "比預期新不算落後")

    def test_trading_days_between_counts_holidays_out(self):
        # 9/16 → 9/22：9/17,9/18,9/21,9/22 = 4（9/19-20 週末不算）
        self.assertEqual(msr._trading_days_between("2026-09-16", "2026-09-22"), 4)
        # 9/23 → 9/30：9/24,9/29,9/30 = 3（9/25 中秋、9/28 教師節、週末不算）
        self.assertEqual(msr._trading_days_between("2026-09-23", "2026-09-30"), 3)

    def test_apply_refuses_stale_basis(self):
        src = (ROOT / "scripts" / "monthly_selfselect_run.py").read_text(encoding="utf-8")
        self.assertIn("拒絕寫入 .env", src)
        self.assertIn("--allow-stale-data", src)
        self.assertIn("--no-refresh-data", src)

    def test_refresh_is_on_by_default(self):
        src = (ROOT / "scripts" / "monthly_selfselect_run.py").read_text(encoding="utf-8")
        self.assertIn('"--refresh-data", action="store_true", default=True', src)


class FetchHoldingsFromVmTest(unittest.TestCase):
    """2026-10-17：從 VM 抓 holdings 時，「VM 上沒有這個檔／空倉」是**合法狀態**（剛從零重來）。"""

    def _fetch(self, rc, stderr='', payload=None):
        import json as _json
        import tempfile
        from scripts.monthly_rebalance_picker import fetch_holdings_from_vm

        class R:
            returncode = rc
            stdout = ''

        with tempfile.TemporaryDirectory() as d:
            dest = Path(d) / 'holdings.json'

            def runner(cmd, capture_output=True, text=True):
                if payload is not None:
                    dest.write_text(_json.dumps(payload), encoding='utf-8')
                r = R()
                r.returncode = rc
                r.stderr = stderr
                return r

            res = fetch_holdings_from_vm(dest=dest, runner=runner)
            return res, (dest.read_text(encoding='utf-8') if dest.exists() else None)

    def test_missing_remote_file_counts_as_flat(self):
        (ok, msg), content = self._fetch(
            1, '/usr/bin/scp: ~/tw-autotrader/logs/holdings.json: No such file or directory')
        self.assertTrue(ok, msg)
        self.assertIn('空倉', msg)
        self.assertEqual((content or '').strip(), '{}', '要建立本機空檔供後續流程使用')

    def test_empty_holdings_is_ok(self):
        (ok, msg), _dest = self._fetch(0, payload={})
        self.assertTrue(ok, msg)
        self.assertIn('0 筆', msg)

    def test_positions_are_reported(self):
        (ok, msg), _dest = self._fetch(0, payload={'3017': 10, '2409': 0})
        self.assertTrue(ok, msg)
        self.assertIn('1 筆', msg)

    def test_other_failures_still_abort(self):
        for err in ('ssh: connect to host x port 22: Connection timed out',
                    'ERROR: (gcloud.compute.scp) PERMISSION_DENIED'):
            (ok, msg), _dest = self._fetch(1, err)
            self.assertFalse(ok, f'{err} 不該被當成空倉')
            self.assertIn('scp 失敗', msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)

class ResolveLegAllocTest(unittest.TestCase):
    """每檔 alloc 的來源與預設（2026-10-17：從零重來後 `.env` 沒有 PC_* ⇒ 舊碼會變 0%／100%）。"""

    def setUp(self):
        from scripts.monthly_selfselect_run import resolve_leg_alloc
        self.f = resolve_leg_alloc

    def test_args_win(self):
        per, leg, src = self.f(cur_leg=30, top_n=5, args_per_name=7.5)
        self.assertEqual((per, src), (7.5, '命令列 --per-name-alloc'))
        per, leg, src = self.f(cur_leg=30, top_n=5, args_leg_pct=40)
        self.assertEqual((per, leg), (8.0, 40.0))

    def test_existing_leg_pct_used_when_present(self):
        per, leg, src = self.f(cur_leg=30, top_n=5)
        self.assertEqual((per, leg), (6.0, 30.0))
        self.assertIn('.env', src)

    def test_empty_env_falls_back_to_default_100pct(self):
        """從零重來後 cur_leg=0 ⇒ 用 SELFSELECT_LEG_PCT（本專案單腿 ⇒ 預設 100%）。

        （多腿時代預設是 30%：自選股腿只分到三條腿的三成。拆成單腿專案後改為 100%，
          想留現金的人自己把 SELFSELECT_LEG_PCT 調低。）
        """
        per, leg, src = self.f(cur_leg=0, top_n=5)
        self.assertEqual(per, 20.0, '預設 100% ÷ 5 = 20%')
        self.assertEqual(leg, 100.0)
        self.assertIn('SELFSELECT_LEG_PCT', src)

    def test_env_override(self):
        per, leg, src = self.f(cur_leg=0, top_n=5, env_leg_pct=50)
        self.assertEqual((per, leg), (10.0, 50.0))

    def test_picker_suggestion_uses_leg_budget_not_100(self):
        """picker 印的建議 alloc 不得再是固定 100/N（5 檔＝20%、合計 100%）。"""
        src = (Path(__file__).resolve().parent.parent / 'scripts'
               / 'monthly_rebalance_picker.py').read_text(encoding='utf-8')
        self.assertNotIn('alloc = round(100.0 / max(1, len(selected)), 1)', src)
        self.assertIn('SELFSELECT_LEG_PCT', src)
