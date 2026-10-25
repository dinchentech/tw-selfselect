# utils/telegram.py
import os
import time
import requests
from datetime import datetime

TG_MAX_ATTEMPTS = 10   # 429 限流時最多嘗試次數（含首次）
TG_RETRY_DELAY = 3     # 429 限流後延遲秒數


def send_telegram_message(message: str):
    """發送 Telegram 訊息（Markdown 失敗自動降級純文字；429 限流自動延後重試）。"""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("⚠️ Telegram 未設定，跳過通知")
        return False

    base_payload = {
        "chat_id": chat_id,
        "text": f"\U0001f916 TW AutoTrader\n{message}",
    }
    # Markdown → 400 降級純文字
    variants = [
        ("Markdown", {**base_payload, "parse_mode": "Markdown"}),
        ("純文字",   {**base_payload}),
    ]

    for attempt in range(1, TG_MAX_ATTEMPTS + 1):
        for tag, payload in variants:
            try:
                response = requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    json=payload, timeout=10)
            except Exception as e:
                if attempt < TG_MAX_ATTEMPTS:
                    print(f"⚠️ Telegram 連線錯誤，{TG_RETRY_DELAY}秒後重試 ({attempt}/{TG_MAX_ATTEMPTS})")
                    time.sleep(TG_RETRY_DELAY)
                    break
                print(f"❌ Telegram 發送錯誤: {e}")
                return False
            if response.status_code == 200:
                suffix = "" if tag == "Markdown" else "（Markdown 降級為純文字）"
                print(f"✅ Telegram 通知已發送{suffix}")
                return True
            if response.status_code == 429:
                if attempt < TG_MAX_ATTEMPTS:
                    print(f"⚠️ Telegram 429 限流，{TG_RETRY_DELAY}秒後重試 ({attempt}/{TG_MAX_ATTEMPTS})")
                    time.sleep(TG_RETRY_DELAY)
                    break
                print(f"❌ Telegram 發送失敗: 429（重試 {TG_MAX_ATTEMPTS} 次後放棄）")
                return False
            if response.status_code == 400 and tag == "Markdown":
                continue  # 降級純文字（同一 attempt 內改用下一個 variant）
            print(f"❌ Telegram 發送失敗: {response.status_code}")
            return False
    return False


def send_trade_alert(symbol: str, action: str, price: float,
                     quantity: int, strategy: str):
    """發送交易警報"""
    message = (
        f"*{action.upper()} {symbol}*\n"
        f"\U0001f4b0 價格: {price:.2f}\n"
        f"\U0001f4ca 數量: {quantity:,} 股\n"
        f"\U0001f3af 策略: {strategy}\n"
        f"\u23f0 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_telegram_message(message)
