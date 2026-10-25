"""回歸測試：`.env` 是唯一真相——容器建立時注入的舊 `PC_*` 不得殘留。

🐛 2026-10-17 事故：B 腿換股把 6213 換成 8046 後，`.env` 已無 `PC_6213`，但 compose 的
`env_file` 在**建立容器時**就注入 `os.environ`，舊 key 不會消失。`load_portfolio_config()`
只掃 `os.environ` ⇒ 熱重載後印「目前監控 9 檔」（8 檔 ＋ 幽靈 6213），而換股日
`is_rotation_buy()` 只看「keep_wait ＋ max_entry_price=-1 ∧ 換股日」⇒ **會買到上月淘汰的股票**。

修法：`.env` 檔存在時，只認檔內有列出的代號（檔內沒有 ⇒ 直接排除）。
`.env` 不存在時維持舊行為（純 env 部署，如 `docker run -e PC_...`）。
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config_loader import load_portfolio_config

_CFG = '{"strategy": "keep_wait", "alloc": 8.33, "max_entry_price": -1, "initial_buy_pct": 1.0}'


def _env_vars(pc_syms, dotenv_path):
    d = {'DOTENV_PATH': str(dotenv_path)}
    for s in pc_syms:
        d['PC_' + s] = _CFG
    return d


class EnvFileIsSourceOfTruthTest(unittest.TestCase):

    def _run(self, tmp: Path, file_pc_syms, environ_pc_syms, file_exists=True):
        env = tmp / '.env'
        if file_exists:
            lines = ['# ── 排程 B ──'] + [f'PC_{s}={_CFG}' for s in file_pc_syms]
            env.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        with patch.dict(os.environ, _env_vars(environ_pc_syms, env), clear=True):
            return load_portfolio_config()

    def test_stale_env_key_excluded_when_absent_from_file(self):
        """容器殘留 PC_6213、`.env` 只有 6505/1301/8046 ⇒ 只能有 3 檔。"""
        with tempfile.TemporaryDirectory() as d:
            cfg = self._run(Path(d), file_pc_syms=['6505', '1301', '8046'],
                            environ_pc_syms=['6213', '6505', '1301', '8046'])
            self.assertEqual(sorted(cfg), ['1301', '6505', '8046'], f'幽靈代號必須排除：{sorted(cfg)}')
            self.assertNotIn('6213', cfg)

    def test_file_with_zero_pc_lines_means_empty_portfolio(self):
        """`.env` 存在但沒有任何 PC_ 行（清空名單）⇒ 空組合，不沿用 env 殘留。"""
        with tempfile.TemporaryDirectory() as d:
            cfg = self._run(Path(d), file_pc_syms=[], environ_pc_syms=['6213', '6505'])
            self.assertEqual(cfg, {})

    def test_no_env_file_keeps_legacy_env_only_behaviour(self):
        """沒有 `.env` 檔（純 `docker run -e` 部署）⇒ 沿用舊行為，不排除任何 key。"""
        with tempfile.TemporaryDirectory() as d:
            cfg = self._run(Path(d), file_pc_syms=[], environ_pc_syms=['6213', '6505'],
                            file_exists=False)
            self.assertEqual(sorted(cfg), ['6213', '6505'])

    def test_duplicate_in_file_still_doubles_alloc(self):
        """撞股加倍（V4.x 跨排程合併）不能被這次修正破壞。"""
        with tempfile.TemporaryDirectory() as d:
            env = Path(d) / '.env'
            env.write_text(f'PC_2357={_CFG}\nPC_2357={_CFG}\nPC_3231={_CFG}\n', encoding='utf-8')
            with patch.dict(os.environ, _env_vars(['2357', '3231'], env), clear=True):
                cfg = load_portfolio_config()
            self.assertAlmostEqual(cfg['2357']['alloc'], 16.66, places=2)
            self.assertAlmostEqual(cfg['3231']['alloc'], 8.33, places=2)


if __name__ == '__main__':
    unittest.main()
