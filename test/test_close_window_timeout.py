"""回歸測試：收盤前下單窗口的時間預算（2026-10-19）。

## 背景

日 K 策略只在 **13:25–13:30**（收盤前 5 分鐘）判定與下單（`core.live_utils.close_order_window_open`）。
實測正常每檔 1–2 秒，但 2026-10-19 有個 30 秒的卡單（8046）⇒ 每卡一檔就吃掉 30 秒。
玉山下單的外層等待上限 `ESUN_PLACE_ORDER_TIMEOUT`（`data/esun_provider.PLACE_ORDER_TIMEOUT`）
原本 30 秒 ⇒ 多檔同時卡住時，後面的標的會來不及在 13:30 前送出。
⇒ 預設維持 30（行為不變），但**可用 `.env` 調降**（現行 .env 用 15 秒）。

⚠️ 報價（`get_current_price`）的 30 秒讀取逾時是**玉山 SDK 內建**的，不是本專案的程式，
   這一支測試只守住「我們自己那層」的旋鈕。
"""
import importlib
import os
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parent.parent


def _reload_timeout():
    import data.esun_provider as P
    return importlib.reload(P).PLACE_ORDER_TIMEOUT


class PlaceOrderTimeoutKnobTest(unittest.TestCase):

    def test_env_value_honoured(self):
        with patch.dict(os.environ, {'ESUN_PLACE_ORDER_TIMEOUT': '15'}):
            self.assertEqual(_reload_timeout(), 15)

    def test_default_is_30_when_unset(self):
        env = {k: v for k, v in os.environ.items() if k != 'ESUN_PLACE_ORDER_TIMEOUT'}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(_reload_timeout(), 30)

    def test_env_example_documents_knob(self):
        src = (_ROOT / '.env.example.txt').read_text(encoding='utf-8')
        self.assertIn('ESUN_PLACE_ORDER_TIMEOUT', src, '.env.example.txt 必須說明這個旋鈕')

    def test_live_env_value_is_within_window_budget(self):
        """實盤 `.env`（若存在）不可把下單逾時設得比 30 秒還長——5 分鐘窗口塞不下。"""
        env_file = _ROOT / '.env'
        if not env_file.exists():
            self.skipTest('沒有 .env')
        for line in env_file.read_text(encoding='utf-8').splitlines():
            s = line.strip()
            if s.startswith('ESUN_PLACE_ORDER_TIMEOUT='):
                val = s.split('=', 1)[1].split('#')[0].strip()
                self.assertLessEqual(float(val), 30.0, f'逾時 {val}s 太長（窗口只有 5 分鐘）')


class CloseOrderFromEnvTest(unittest.TestCase):
    """`.env.example.txt` 長期寫著 `CLOSE_ORDER_FROM` 可調，但程式是寫死常數（改了沒反應）。

    2026-10-19 改成讀 env；預設值仍 13:25 ⇒ 沒設定的環境行為完全不變。
    """

    def _reload_from(self, value):
        import core.live_utils as L
        with patch.dict(os.environ, {'CLOSE_ORDER_FROM': value}):
            return importlib.reload(L).CLOSE_ORDER_FROM

    def test_env_overrides(self):
        self.assertEqual(self._reload_from('13:20'), '13:20')

    def test_default_when_unset(self):
        env = {k: v for k, v in os.environ.items() if k != 'CLOSE_ORDER_FROM'}
        with patch.dict(os.environ, env, clear=True):
            import core.live_utils as L
            self.assertEqual(importlib.reload(L).CLOSE_ORDER_FROM, '13:25')


class CloseOrderWindowBoundsTest(unittest.TestCase):
    """窗口本身只有起點（>= 13:25）；收盤 13:30 是硬邊界，這裡把語義釘住。"""

    def test_window_opens_at_1325_and_has_no_upper_bound(self):
        # 明確帶 start：本測試驗「窗口語義」，不受其他測試改動模組常數影響
        from datetime import datetime
        from core.live_utils import close_order_window_open
        self.assertFalse(close_order_window_open(datetime(2026, 10, 19, 13, 24), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 25), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 29), start='13:25'))
        self.assertTrue(close_order_window_open(datetime(2026, 10, 19, 13, 31), start='13:25'))


if __name__ == '__main__':
    unittest.main()
