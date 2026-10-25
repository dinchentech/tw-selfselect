"""回歸測試：Telegram 429 限流自動重試（延 3 秒、最多 10 次）+ Markdown 降級。

背景：2026-09-08 系統通知曾出現「❌ Telegram 發送失敗: 429」（rate limit），
兩則通知沒發出去。新增 429 → 延後重試，避免單次通知因限流漏發。
本測試用 mock 驗證重試次數/延遲/Markdown 降級行為（不真的發送、不真的等待）。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import telegram as tg


class FakeResp:
    def __init__(self, status):
        self.status_code = status


class TestTelegramRetry(unittest.TestCase):
    def setUp(self):
        os.environ["TELEGRAM_BOT_TOKEN"] = "TEST_TOKEN"
        os.environ["TELEGRAM_CHAT_ID"] = "TEST_CHAT"

    @mock.patch("utils.telegram.time.sleep", return_value=None)
    @mock.patch("utils.telegram.requests.post")
    def test_ok_first_try_no_retry(self, mock_post, mock_sleep):
        mock_post.return_value = FakeResp(200)
        self.assertTrue(tg.send_telegram_message("hi"))
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @mock.patch("utils.telegram.time.sleep", return_value=None)
    @mock.patch("utils.telegram.requests.post")
    def test_429_then_200_retries_with_delay(self, mock_post, mock_sleep):
        mock_post.side_effect = [FakeResp(429), FakeResp(429), FakeResp(200)]
        self.assertTrue(tg.send_telegram_message("hi"))
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # 兩次 429 都延後

    @mock.patch("utils.telegram.time.sleep", return_value=None)
    @mock.patch("utils.telegram.requests.post")
    def test_429_exhausted_returns_false_after_10(self, mock_post, mock_sleep):
        mock_post.return_value = FakeResp(429)
        self.assertFalse(tg.send_telegram_message("hi"))
        self.assertEqual(mock_post.call_count, 10)  # 最多試 10 次
        self.assertEqual(mock_sleep.call_count, 9)  # 前 9 次 429 都延後

    @mock.patch("utils.telegram.time.sleep", return_value=None)
    @mock.patch("utils.telegram.requests.post")
    def test_400_degrade_to_plain_ok(self, mock_post, mock_sleep):
        mock_post.side_effect = [FakeResp(400), FakeResp(200)]  # Markdown→400, 純文字→200
        self.assertTrue(tg.send_telegram_message("hi"))
        self.assertEqual(mock_post.call_count, 2)

    @mock.patch("utils.telegram.time.sleep", return_value=None)
    @mock.patch("utils.telegram.requests.post")
    def test_other_status_fails(self, mock_post, mock_sleep):
        mock_post.return_value = FakeResp(500)
        self.assertFalse(tg.send_telegram_message("hi"))
        self.assertEqual(mock_post.call_count, 1)

    def test_no_token_skips(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        self.assertFalse(tg.send_telegram_message("hi"))


if __name__ == "__main__":
    unittest.main()
