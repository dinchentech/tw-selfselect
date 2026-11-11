# utils/telegram.py
import os
import re
import time
import requests
from datetime import datetime

TG_MAX_ATTEMPTS = 10   # 429 限流時最多嘗試次數（含首次）
TG_RETRY_DELAY = 3     # 429 限流後延遲秒數

# legacy Markdown（parse_mode="Markdown"）的特殊字元。`]` 不必轉義（只有 `[` 會開連結）。
_MD_SPECIAL = re.compile(r"([_*`\[])")


def escape_md(text) -> str:
    """轉義 legacy Markdown 的特殊字元，**只用在動態內容**上（2026-11-09）。

    為什麼需要：Telegram 的 `parse_mode="Markdown"`（legacy）把 `_`／`*`／`` ` ``／`[` 當標記，
    動態內容只要落單一個就會 `400 Bad Request: can't parse entities`，整則訊息被降級成純文字
    （使用者看到的是「格式掉了」，程式碼只印一行「Markdown 降級為純文字」）。

    實例（本專案很容易踩到的三個）：
      · 策略名稱 `keep_wait`／`ma_cross`（底線）
      · 券商／對帳狀態 `broker_mismatch`、`ledger_mismatch`、`auto_resolved.json`
      · 例外字串（`invalid literal for int()` 之類）

    用法：訊息本身的靜態 `*粗體*` 留在外面，動態值包起來——
    `f'🅿️ *停泊釋出*\\n{sym} 賣出 {done} 股\\n原因：{escape_md(reason)}'`。
    """
    if text is None:
        return ""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def md_ok(text) -> bool:
    """粗檢 legacy Markdown 標記是否成對（成對才不會被 Telegram 判為 entity 解析錯誤）。

    規則：`*`／`_`／`` ` `` 的未轉義出現次數必須是偶數，`[` 與 `]` 數量必須相等。
    這不是完整的 Markdown 解析器——只用來**在送出前發現明顯的落單標記**，
    命中就別浪費一次 API 呼叫與 400 往返，直接發純文字並印出肇因。
    """
    s = "" if text is None else str(text)
    unescaped = re.sub(r"\\[_*`\[\]]", "", s)   # 先去掉已轉義的（`\_`、`\*` …）
    if any(unescaped.count(ch) % 2 for ch in ("*", "_", "`")):
        return False
    return unescaped.count("[") == unescaped.count("]")


def send_telegram_message(message: str):
    """發送 Telegram 訊息（Markdown 失敗自動降級純文字；429 限流自動延後重試）。

    2026-11-09：送出前先用 `md_ok()` 檢查標記是否成對。不成對就直接發純文字並印出肇因——
    以前是送出 → 400 → 降級，成功那行只寫「降級為純文字」，看不出是哪一則、為什麼
    （實測每天至少一則，`keep_wait` 這種底線是主因）。動態內容請先過 `escape_md()`。
    """
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("⚠️ Telegram 未設定，跳過通知")
        return False

    base_payload = {
        "chat_id": chat_id,
        "text": f"\U0001f916 TW SelfSelect\n{message}",
    }
    # Markdown → 400 降級純文字
    variants = [("Markdown", {**base_payload, "parse_mode": "Markdown"}),
                ("純文字", {**base_payload})]
    if not md_ok(base_payload["text"]):
        # 已知必定 400：省掉一次往返，並把「哪一則壞了」印出來（否則只能從「降級」猜）
        _head = str(message).replace("\n", " / ")[:80]
        print(f"⚠️ Telegram 訊息 Markdown 標記不成對（落單的 * _ ` [）⇒ 直接發純文字：{_head}")
        variants = variants[1:]

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
                _head = str(message).replace("\n", " / ")[:80]
                print(f"⚠️ Telegram Markdown 被拒（400）⇒ 降級純文字：{_head}")
                continue  # 降級純文字（同一 attempt 內改用下一個 variant）
            print(f"❌ Telegram 發送失敗: {response.status_code}")
            return False
    return False


def send_trade_alert(symbol: str, action: str, price: float,
                     quantity: int, strategy: str):
    """發送交易警報（動態值全部轉義：`strategy` 可能是 `MA_CROSS` 這種有底線的）"""
    message = (
        f"*{escape_md(action.upper())} {escape_md(symbol)}*\n"
        f"\U0001f4b0 價格: {price:.2f}\n"
        f"\U0001f4ca 數量: {quantity:,} 股\n"
        f"\U0001f3af 策略: {escape_md(strategy)}\n"
        f"\u23f0 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_telegram_message(message)
