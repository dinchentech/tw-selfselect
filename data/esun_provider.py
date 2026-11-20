"""E.Sun (玉山證券) broker provider — market data + order execution

Wraps esun_marketdata + esun_trade SDKs into the same interface as kgi_mock/kgi_real.
Used when BROKER=esun in .env.

Config sources (priority order):
  1. ESUN_CONFIG_INI env var → read that .ini file directly
  2. esun_sdk/config.simulation.ini.example (auto-detect, if exists)
  3. Individual ESUN_* env vars (fallback)

The .p12 cert path in the loaded .ini is overridden by ESUN_CERT_PATH (if set)
or auto-resolved to esun_sdk/*.p12 (if the default ini is used).

Passwords are stored in system keyring. Can be pre-populated via env vars:
  ESUN_ACCOUNT_PASSWORD=...
  ESUN_CERT_PASSWORD=...

One-time interactive password setup:
  python -c "from data.esun_provider import EsunProvider; EsunProvider().interactive_setup()"
"""

import os
import sys
import time
import glob
import threading
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone
from configparser import ConfigParser

from esun_marketdata import EsunMarketdata
from esun_trade.sdk import SDK as EsunTrade
from esun_trade.order import OrderObject
from esun_trade.constant import Action, APCode, PriceFlag, Trade, BSFlag

# 整股（board lot）規則的單一出處（2026-11-09，v1.1.36）——見 core/lots.py 的事故說明
from core.lots import LOT, ODD_LOT_MAX, board_lot_qty
from utils.telegram import escape_md

# Default path relative to project root
_DEFAULT_INI = "esun_sdk/config.simulation.ini"

# E.Sun SDK 偶發無限阻塞凍結主程式，下單等待上限秒（可被 ESUN_PLACE_ORDER_TIMEOUT 覆寫）
PLACE_ORDER_TIMEOUT = int(os.getenv("ESUN_PLACE_ORDER_TIMEOUT", "30"))

# E.Sun 編譯核心（_trade_core.abi3.so）在 ESUN_DEBUG=true 時會自己印出原始回應；
# 那行錯誤訊息本身就是這樣寫的：「A00002: response parse Error, use env variable
# "ESUN_DEBUG=true" in command line to see what happened」。
# 這裡只補上核心看不到的「我方送出的內容」與完整 traceback。
ESUN_DEBUG = os.getenv("ESUN_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")

# 報價重試次數（逾時／斷線才重試；其他錯誤不重試）。2026-11-04：每次重試之間退避 0.4 秒，
# 讓同一檔連續逾時不會把 13:25–13:30 的下單窗口全部吃掉。
NET_QUOTE_RETRIES = max(1, int(os.getenv("NET_QUOTE_RETRIES", "2")))
NET_QUOTE_BACKOFF_SEC = float(os.getenv("NET_QUOTE_BACKOFF_SEC", "0.4"))

# ── 玉山取不到價 → 改抓 TWSE MIS（2026-11-16，v1.1.42）────────────────────
# 為什麼：2408 每天 09:00 開盤首圈必定逾時（8+8 秒換 `px=0`，合成當日 K 少一分鐘）。MIS 是現成的
#   第二來源（持倉報告／儀表板本來就在用 `core.inst_data.fetch_intraday_quotes`），不新增依賴。
# ⚠️ **永不退昨收**（`y`）：把昨收當今天價格會讓停泊／買進股數用錯價，比回 0 更糟
#   （見 `fetch_intraday_quotes(allow_prev_close=False)`）。可用順序＝`z` 當日最後成交價
#   → **成形價（最佳買賣價中價）**→ 不給。成形價是 2026-11-17 補的：`z` 只在「剛好有撮合到」
#   的 snapshot 才有（抽 12 檔只有 3 檔有值；2615／2609／2603 連測 8 次全沒有，只認 `z` 的備援
#   對那三檔等於不存在），而五檔 `b`/`a` 12/12 都有值。
# 想整支關掉：`.env` 設 `ESUN_MIS_QUOTE_FALLBACK=0`（重啟容器生效）。
MIS_QUOTE_FALLBACK = os.getenv("ESUN_MIS_QUOTE_FALLBACK", "1").strip().lower() not in (
    "0", "false", "no", "off")
_MIS_QUOTE_TIMEOUT_SEC = 3          # 備援只值這麼多秒：本體已經卡掉 16 秒，13:25–13:30 窗口要塞多檔
                                    #   ⇒ 最壞每檔 16.4 + 2×3 秒（MIS 是 cookie＋查詢兩個請求）


def _tpe_ts() -> str:
    """台北時間 `HH:MM:SS`：報價診斷行的前綴。

    為什麼（2026-11-17）：這些 print 原本**沒有時間戳**，貼出來的 log 看起來永遠像「啟動就出事」——
    11/16 與 11/17 兩次都得回頭跑 `docker logs -t` 再換算（`-t` 是 **UTC**，`01:00:12Z` ＝ 台北 09:00:12）。
    容器時區是 UTC ⇒ 這裡明確換算成 UTC+8（台灣無夏令時間，固定 +8 即可）。
    """
    return datetime.now(timezone(timedelta(hours=8))).strftime("%H:%M:%S")

# ── 缺價→恢復的紀錄（2026-11-16，v1.1.41）─────────────────────────────────
# 為什麼需要：**成功的報價完全不落紀錄**，`⚠️/❌` 只印失敗 ⇒「開盤第一圈逾時、下一圈恢復」
#   這種形狀在 log 上只剩「一次失敗」，看不出到底恢復了沒有（2026-11-16 查 2408 就卡在這裡：
#   只能靠「沒有第二筆 ⚠️」反推，而 `get_current_price` 還有兩條靜默回 0 的路徑）。
# 做法：缺價時記住**第一次**失敗的時間，同一檔下次拿到正價格時印**一行**
#   `✅ 2408 報價已恢復（377.00，缺價 68 秒）`。正常盤零輸出，不會洗版。
# ⚠️ 2026-11-17 更正：原本只記「兩次都失敗（❌）」，於是**「⚠️ 之後重試就成功」完全不會印 ✅**
#   ——而那是每天 09:00 都會發生的形狀，等於最該被證明的情況沒有證據（11/17 只能靠「沒有 ❌」反推）。
#   現在**中途逾時也記**，重試成功時照樣印 ✅。
_quote_missing = {}                 # {symbol: 第一次失敗的 time.time()}


def quote_missing_snapshot():
    """目前仍在缺價的標的 `{symbol: 第一次失敗的 epoch 秒}`（測試／診斷用；含「重試中」的那一刻）。"""
    return dict(_quote_missing)


def _note_quote_failed(symbol):
    """記住第一次失敗的時間（同檔連續失敗不覆寫，缺價秒數才不會被重試洗短）。"""
    _quote_missing.setdefault(str(symbol), time.time())


def _note_quote_recovered(symbol, price):
    """拿到**正價格**時，若先前缺價就印一行恢復訊息並清除紀錄。"""
    try:
        px = float(price)
    except (TypeError, ValueError):
        return
    if px <= 0:
        return                      # 回 0 ＝ 還是沒有價（例如回應沒有 lastPrice），不算恢復
    started = _quote_missing.pop(str(symbol), None)
    if started is None:
        return
    print(f"[{_tpe_ts()}] ✅ {symbol} 報價已恢復（{px:.2f}，缺價 {max(0.0, time.time() - started):.0f} 秒）")

# 「重登重試也救不回來」的下單錯誤：時間／盤別類。含這些字樣就不做強制重登重試
# （2026-11-04 VM：13:45 停泊單被退 000017，重登後重試必再失敗，只是多打一次 API）。
NON_RETRYABLE_ORDER_ERRORS = (
    "000017",                    # 非該盤別盤中或預約時間，停止收單
    "非該盤別盤中或預約時間",
)


def is_non_retryable_order_error(err) -> bool:
    """下單錯誤是否屬於「重試無用」（時間／盤別錯）。None／空字串 → False。"""
    s = str(err or "")
    return any(tok in s for tok in NON_RETRYABLE_ORDER_ERRORS)


def _resolve_cert_path(cfg):
    """Resolve .p12 cert path: env override > auto-detect in esun_sdk/ > ini value."""
    env_path = os.getenv("ESUN_CERT_PATH")
    if env_path:
        return env_path
    # Auto-detect: if using default ini, look for any .p12 in esun_sdk/
    ini_path = cfg.get("Cert", "Path", fallback="")
    if not ini_path or ini_path.strip().startswith(";"):
        p12_files = glob.glob("esun_sdk/*.p12")
        if p12_files:
            return os.path.abspath(p12_files[0])
    return ini_path


def load_config():
    """Load E.Sun SDK config from best available source."""
    cfg = ConfigParser()

    # Source 1: explicit ESUN_CONFIG_INI env var
    ini_file = os.getenv("ESUN_CONFIG_INI")
    if ini_file and os.path.exists(ini_file):
        cfg.read(ini_file)
        _apply_cert_override(cfg)
        return cfg

    # Source 2: auto-detect default ini
    if os.path.exists(_DEFAULT_INI):
        cfg.read(_DEFAULT_INI)
        _apply_cert_override(cfg)
        return cfg

    # Source 2b: fallback to .example (使用者還沒複製 .ini 時可暫用)
    example_ini = "esun_sdk/config.simulation.ini.example"
    if os.path.exists(example_ini):
        cfg.read(example_ini)
        _apply_cert_override(cfg)
        return cfg

    # Source 3: build from individual env vars
    cfg.add_section("Core")
    cfg.set("Core", "Entry", os.getenv("ESUN_ENTRY", ""))
    cfg.set("Core", "Environment", os.getenv("ESUN_ENVIRONMENT", "simulation"))
    cfg.add_section("Cert")
    cfg.set("Cert", "Path", _resolve_cert_path(cfg))
    cfg.add_section("Api")
    cfg.set("Api", "Key", os.getenv("ESUN_API_KEY", ""))
    cfg.set("Api", "Secret", os.getenv("ESUN_API_SECRET", ""))
    cfg.add_section("User")
    cfg.set("User", "Account", os.getenv("ESUN_ACCOUNT", ""))
    return cfg


def _apply_cert_override(cfg):
    """Override cert path in loaded config with resolved value."""
    if not cfg.has_section("Cert"):
        cfg.add_section("Cert")
    resolved = _resolve_cert_path(cfg)
    if resolved:
        cfg.set("Cert", "Path", resolved)


class EsunProvider:
    """玉山證券 broker provider — 符合 KGI 相容介面"""

    def __init__(self):
        self.config = load_config()
        self._marketdata = None
        self._trade_sdk = None
        self._logged_in = False
        self._login_failed = False
        # ── 登入狀態一律以「日期」為界 ──────────────────────────────
        # 玉山 session token 的效期只到**簽發當日 23:59:59**（JWT `exp` 實測），
        # 所以跨日就必須重登；否則 container 跨夜執行時，隔天開盤仍拿著昨天的
        # 過期 token → 下單持續回 `A00002: response parse Error`（2026-08-31、
        # 2026-09-11 兩次事故，都只能靠人工重啟恢復）。
        self._session_date = None        # 上述狀態所屬的日期（YYYY-MM-DD）
        self._md_date = None             # marketdata 登入成功的日期
        self._trade_date = None          # trade 登入成功的日期
        self._trade_failed_date = None   # trade 登入失敗的日期（同日不再重試）

        # Pre-populate keyring from env vars (for headless/Docker usage)
        self._seed_keyring_from_env()

    # ── 登入狀態（日期邊界）──────────────────────────────────────

    @staticmethod
    def _today():
        return datetime.now().strftime("%Y-%m-%d")

    def _roll_day_if_needed(self):
        """跨日時清掉所有日界登入狀態，讓下一次 login() 真的重登。"""
        today = self._today()
        if self._session_date == today:
            return
        self._logged_in = False
        self._login_failed = False
        self._md_date = None
        self._trade_date = None
        self._trade_failed_date = None
        self._session_date = today

    # ── keyring helpers ──────────────────────────────────────────

    @staticmethod
    def _ensure_keyring():
        """Force CryptFileKeyring globally so both our code and SDK use the same backend + key."""
        from keyring import set_keyring
        from keyrings.cryptfile.cryptfile import CryptFileKeyring
        os.environ.setdefault("PYTHON_KEYRING_BACKEND",
                              "keyrings.cryptfile.cryptfile.CryptFileKeyring")
        # ⚠️ 不提供預設值：cryptfile 的密碼就是「金鑰庫的解鎖密碼」，寫死在程式裡等於沒有保護。
        #    Docker／headless 請在環境變數或 `.env` 設定；互動環境會提示輸入。
        if not os.environ.get("KEYRING_CRYPTFILE_PASSWORD"):
            raise RuntimeError(
                "未設定 KEYRING_CRYPTFILE_PASSWORD（金鑰庫解鎖密碼）。"
                "請在 .env 或容器環境變數設定一個只有你知道的隨機字串，"
                "例如：KEYRING_CRYPTFILE_PASSWORD=$(openssl rand -hex 16)")
        kr = CryptFileKeyring()
        kr.keyring_key = os.environ["KEYRING_CRYPTFILE_PASSWORD"]
        set_keyring(kr)

    def _seed_keyring_from_env(self):
        """If ESUN_ACCOUNT_PASSWORD / ESUN_CERT_PASSWORD set, store in keyring."""
        from keyring import set_password, get_password
        from esun_marketdata.util import TRADE_SDK_ACCOUNT_KEY, TRADE_SDK_CERT_KEY

        account = self.config.get("User", "Account", fallback="") if self.config.has_section("User") else ""
        if not account:
            return

        self._ensure_keyring()

        ap = os.getenv("ESUN_ACCOUNT_PASSWORD")
        if ap and not get_password(TRADE_SDK_ACCOUNT_KEY, account):
            set_password(TRADE_SDK_ACCOUNT_KEY, account, ap)

        cp = os.getenv("ESUN_CERT_PASSWORD")
        if cp and not get_password(TRADE_SDK_CERT_KEY, account):
            set_password(TRADE_SDK_CERT_KEY, account, cp)

    @classmethod
    def interactive_setup(cls):
        """Interactive password setup (run once)."""
        from esun_marketdata.util import ft_set_password as md_setpwd
        from esun_trade.util import ft_set_password as tr_setpwd
        cfg = load_config()
        account = cfg.get("User", "Account", fallback="") if cfg.has_section("User") else ""
        if not account:
            print("Cannot determine ESUN_ACCOUNT. Check that esun_sdk/config.simulation.ini.example exists or set ESUN_ACCOUNT env var.")
            return
        print(f"Setting keyring passwords for account {account}…")
        md_setpwd(account)
        tr_setpwd(account)
        print("Done. Passwords stored in system keyring.")

    # ── login ────────────────────────────────────────────────────

    def login(self):
        """Login to both market-data and trade SDKs.

        ⚠️ 登入狀態以「日期」為界：玉山 session token 效期只到簽發當日 23:59:59，
        跨日必須重登（見 `_roll_day_if_needed`）。同日內則不重複登入，避免每次
        報價都打一次 auth。
        """
        self._roll_day_if_needed()
        today = self._session_date

        # ── marketdata（失敗則當日不再嘗試，`_ensure_available` 會跟著回 False）──
        if (self._md_date != today) and (not self._login_failed):
            try:
                self._marketdata = EsunMarketdata(self.config)
                self._marketdata.login()
                self._md_date = today
            except ValueError as e:
                error_msg = str(e)
                if "AGA0000" in error_msg or "系統維護" in error_msg:
                    print(f"\n❌ 玉山 API 維護中（08:00-13:00）")
                    print(f"   錯誤訊息: {error_msg}")
                    print(f"   程式將在 3 分鐘後自動退出，請避開維護時間再重啟")

                    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                    chat_id = os.getenv("TELEGRAM_CHAT_ID")
                    if bot_token and chat_id:
                        # 2026-11-09：錯誤字串是動態內容（可能含 `_`／`*`）⇒ 先轉義，
                        #   否則 legacy Markdown 解析失敗、整則 400（這裡沒有降級重送）
                        _err_md = escape_md(error_msg)
                        msg = (
                            f"⚠️ *玉山 API 維護中*\n\n"
                            f"錯誤: {_err_md}\n\n"
                            f"維護時間: 08:00-13:00\n"
                            f"程式將在 3 分鐘後退出\n"
                            f"請避開維護時間再重啟\n\n"
                            f"⏰ 當前時間: {datetime.now().strftime('%H:%M')}"
                        )
                        try:
                            requests.post(
                                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                                timeout=10)
                        except Exception:
                            pass

                    time.sleep(180)
                    sys.exit(1)
                else:
                    print(f"⚠️ E.Sun marketdata login failed: {e}")
                    self._login_failed = True
                    return
            except Exception as e:
                print(f"⚠️ E.Sun marketdata login exception: {e}")
                self._login_failed = True
                return

        # ── trade SDK ─────────────────────────────────────────────
        # 失敗時**不可**把狀態標成「已登入」——舊版無條件設 `_logged_in = True`，
        # 導致 login() 從此 no-op、下單全敗卻沒有任何重試機會。
        if (self._trade_date != today) and (self._trade_failed_date != today):
            try:
                self._trade_sdk = EsunTrade(self.config)
                self._trade_sdk.login()
                self._trade_date = today
            except Exception as e:
                print(f"⚠️  E.Sun trade SDK login failed (market data still works): {e}")
                self._trade_sdk = None      # 不留半死的 SDK 實例
                self._trade_failed_date = today

        # `_logged_in` 改為推導值：兩個 SDK 都必須是「今天的」session
        self._logged_in = (self._md_date == today) and (self._trade_date == today)

    def force_relogin(self):
        """強制重新登入（同日內也真的重做）。

        用於下單失敗時重置所有日界登入狀態，讓 `login()` 重建 SDK 並重登。
        2026-09-11 事件：`login()` 的 `if self._logged_in: return` 讓失效 session
        永遠不重登，3515/2006 連 35 敗、0 成交，靠重啟才恢復。"""
        try:
            self._logged_in = False
            self._login_failed = False
            self._md_date = None
            self._trade_date = None
            self._trade_failed_date = None
            self._session_date = None
            self._trade_sdk = None
            self._marketdata = None
            self.login()
        except Exception as e:
            print(f"⚠️  E.Sun 強制重登失敗: {e}")

    # ── data helpers ─────────────────────────────────────────────

    @staticmethod
    def _candles_to_df(data_list):
        """Convert E.Sun candles JSON → DataFrame with columns open/high/low/close/volume."""
        rows = []
        for d in data_list:
            rows.append({
                "open":   float(d.get("open", 0)),
                "high":   float(d.get("high", 0)),
                "low":    float(d.get("low", 0)),
                "close":  float(d.get("close", 0)),
                "volume": float(d.get("volume", 0)),
            })
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, index=[pd.to_datetime(d["date"]) for d in data_list])
        return df

    # ── market data interface ────────────────────────────────────

    def _ensure_available(self):
        """確認 API 可用，登入失敗或尚未登入時回傳 False

        ⚠️ `_login_failed` 是**日界**狀態：跨日要重新給機會，否則昨天的一次登入
        失敗會讓程式永久回 False（連行情都拿不到，也就不會呼叫 login() 去恢復）。
        """
        self._roll_day_if_needed()
        if self._login_failed:
            return False
        return True

    def get_current_price(self, symbol: str) -> float:
        """即時報價（最後成交價）

        ⚠️ 網路層逾時／斷線**重試一次**（2026-11-02）：報價請求的上限由主程式的
        `NET_QUOTE_TIMEOUT_SEC`（預設 8 秒）控制，一次卡滿就吃掉 13:25–13:30 下單窗口的
        1/10；重試一次的總預算（8+8=16 秒）仍與原本一檔卡 30 秒同級，不會讓
        `place_order` 的外層 `ESUN_PLACE_ORDER_TIMEOUT` 多等。
        只對「逾時／連線錯誤」重試——其他錯誤（參數錯、token 失效）重試無意義。

        📌 2026-11-16（v1.1.41）：失敗會記進 `_quote_missing`，同一檔下次拿到正價格時印一行
        `✅ 2408 報價已恢復（377.00，缺價 68 秒）` ⇒ 「一次失敗之後到底有沒有恢復」不必再靠
        「沒有第二筆 ⚠️」反推（見模組上方說明）。
        📌 2026-11-17：**中途**逾時（＝重試前那一次）也記 ⇒ 「⚠️ 之後重試就成功」這種每天 09:00
        都會出現的形狀，現在會緊接印一行 `✅ … 報價已恢復（109.50，缺價 4 秒）`。

        🩹 2026-11-16（v1.1.42）：玉山**全部失敗**（含「有回應但沒有 `lastPrice`」）時改抓
        TWSE MIS 的當日最後成交價，印 `🩹 2408 玉山取價失敗（…）⇒ 改用 TWSE MIS 備援價 377.00`；
        MIS 也拿不到就照舊回 `0.0`（呼叫端行為完全不變）。MIS 只有昨收時**不使用**。
        """
        if not self._ensure_available():
            return 0.0
        self.login()
        for _attempt in range(1, NET_QUOTE_RETRIES + 1):
            try:
                q = self._marketdata.rest_client.stock.intraday.quote(symbol=symbol)
                px = float(q.get("lastPrice", 0))
                if px > 0:
                    _note_quote_recovered(symbol, px)
                    return px
                _note_quote_failed(symbol)       # 有回應但沒有成交價 ⇒ 對呼叫端就是「沒價」
                return self._mis_fallback_price(symbol, "回應沒有 lastPrice")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                if _attempt < NET_QUOTE_RETRIES:
                    # ⚠️ 2026-11-17：**中途**逾時也要記進 `_quote_missing`，否則「重試就成功」
                    #   這個每天 09:00 都會發生的形狀永遠印不出 ✅ 恢復——v1.1.41 只記「兩次都失敗」，
                    #   結果還是只能靠「沒有 ❌」反推（11/17 09:00 就是這樣，查 log 才敢下結論）。
                    _note_quote_failed(symbol)
                    print(f"[{_tpe_ts()}] ⚠️ {symbol} 報價逾時／斷線，第 {_attempt}/{NET_QUOTE_RETRIES - 1} 次重試"
                          f"（退避 {NET_QUOTE_BACKOFF_SEC}s，{e}）")
                    try:
                        time.sleep(NET_QUOTE_BACKOFF_SEC)
                    except Exception:
                        pass
                    continue
                _note_quote_failed(symbol)
                print(f"[{_tpe_ts()}] ❌ E.Sun get_current_price error: {e}")
                return self._mis_fallback_price(symbol, "逾時／斷線")
            except Exception as e:
                _note_quote_failed(symbol)
                print(f"[{_tpe_ts()}] ❌ E.Sun get_current_price error: {e}")
                return self._mis_fallback_price(symbol, "其他錯誤")
        return 0.0

    def _mis_fallback_price(self, symbol, reason: str) -> float:
        """玉山取價失敗後的備援：TWSE MIS 的**今天**的價（拿不到就回 `0.0`，與 v1.1.41 相同）。

        取價順序（在 `core.inst_data._parse_mis_quotes` 內）：當日最後成交價 `z`
        → **最佳買賣價中價（成形價）** → 不給。**永不退昨收**——昨收當今天價格會讓停泊／
        買進股數用錯價，比回 0 更糟。

        ⚠️ 為什麼要成形價（2026-11-17 實測）：MIS 的 `z` 只在「剛好有撮合到」的 snapshot 才有，
        隨機抽 12 檔只有 3 檔有值；2615／2609／2603 連測 8 次（24 秒）**一次都沒有** `z`
        （同批 2408 是 8/8 都有）⇒ 只認 `z` 的備援對那三檔等於不存在。五檔買賣價 `b`／`a`
        同期 12/12 都有值 ⇒ 補這一階（成形價是今天的價，不是昨收）。

        任何例外都不外拋（報價路徑不可因備援而炸）。
        """
        if not MIS_QUOTE_FALLBACK:
            return 0.0
        try:
            from core.inst_data import fetch_intraday_quotes
            q = (fetch_intraday_quotes([str(symbol)], timeout=_MIS_QUOTE_TIMEOUT_SEC,
                                       allow_prev_close=False) or {}).get(str(symbol)) or {}
            px = float(q.get("price") or 0)
        except Exception:
            return 0.0
        if px <= 0:
            return 0.0
        _quote_missing.pop(str(symbol), None)    # 有價了就不算缺價（不再印 ✅，這行已說明來源）
        if (q.get("source") or "last") == "bid_ask_mid":
            print(f"[{_tpe_ts()}] 🩹 {symbol} 玉山取價失敗（{reason}）⇒ 改用 TWSE MIS 成形價 {px:.2f}"
                  f"（該檔此刻無成交價，取最佳買賣價中價）")
        else:
            print(f"[{_tpe_ts()}] 🩹 {symbol} 玉山取價失敗（{reason}）⇒ 改用 TWSE MIS 備援價 {px:.2f}")
        return px

    def get_historical_data(self, symbol: str, days: int = 30) -> pd.DataFrame:
        """歷史日 K (OHLCV) — 用於初始化累積資料"""
        return self.get_historical_range(symbol, 
            start=(datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"))

    def get_historical_range(self, symbol: str, start: str = "2023-01-01",
                              end: str = "") -> pd.DataFrame:
        """歷史日 K 起訖日期版 — 用於回測"""
        if not self._ensure_available():
            return pd.DataFrame()
        self.login()
        try:
            resp = self._marketdata.rest_client.stock.historical.candles(
                symbol=symbol,
                **{"from": start},
                to=end or datetime.now().strftime("%Y-%m-%d"),
                timeframe="D",
                fields="open,high,low,close,volume",
            )
            df = self._candles_to_df(resp.get("data", []))
            if not df.empty:
                df = df.sort_index()
            return df
        except Exception as e:
            print(f"❌ E.Sun get_historical_range error: {e}")
            return pd.DataFrame()

    def get_minute_bars(self, symbol: str, minutes: int = 60) -> pd.DataFrame:
        """盤中分鐘 K (OHLCV) — 用於即時訊號計算"""
        if not self._ensure_available():
            return pd.DataFrame()
        self.login()
        try:
            resp = self._marketdata.rest_client.stock.intraday.candles(
                symbol=symbol, timeframe="1"
            )
            data = resp.get("data", [])
            if not data:
                return pd.DataFrame()
            if len(data) > minutes:
                data = data[-minutes:]
            return self._candles_to_df(data)
        except Exception as e:
            print(f"❌ E.Sun get_minute_bars error: {e}")
            return pd.DataFrame()

    # ── order execution interface ────────────────────────────────

    def place_order(self, symbol: str, action: str, quantity: int):
        """下單（限價），依股數自動選擇盤中零股或整股

        ⚠️ SDK 呼叫可能無限阻塞（曾造成交易主執行緒凍結數小時），
        故包在 daemon thread 中執行，超過 PLACE_ORDER_TIMEOUT 秒即放棄，
        回傳 {"error": ...} 讓呼叫方 rollback，主程式保持運作。
        """
        if self._trade_sdk is None:
            print("❌ E.Sun trade SDK not available – login failed earlier")
            return {"error": "trade SDK not available"}

        result_holder = {}

        def _do_place(sym, act, qty):
            try:
                buy_sell = Action.Buy if act.upper() == "BUY" else Action.Sell
                price = self.get_current_price(sym)
                if price <= 0:
                    # 取不到報價也可能是 session（行情 token）失效 → 先重登再試一次，
                    # 否則會直接 return，把下面的「失敗重登重試」整段繞過。
                    print(f"⚠️ {sym} 取不到報價 → 強制重登後重試一次")
                    try:
                        self.force_relogin()
                    except Exception as _re:
                        print(f"⚠️ 強制重登失敗: {_re}")
                    price = self.get_current_price(sym)
                if price <= 0:
                    result_holder["error"] = "cannot get current price"
                    return
                # 實際送單價（2026-10-19）：這裡的 price 是「送單前重新取的現價」，
                # 常與上層的決策價（選股日收盤／上一根K）不同 —— 6505 當天決策價 123.0、
                # 實際送單 123.50。帶回上層才能記到與券商一致的成本。
                result_holder["sent_price"] = float(price)

                # 999 股以下走盤中零股，以上走整股
                if qty <= ODD_LOT_MAX:
                    ap_code = APCode.IntradayOdd
                    order_type = "盤中零股"
                else:
                    ap_code = APCode.Common
                    order_type = "整股"
                    # 整股四捨五入至整張（ESun Common APCode 以「張」為單位）。
                    # 2026-11-09（v1.1.36）：規則已收斂到 `core/lots.board_lot_qty()`，上層買單 sizing
                    #   與停泊都先對齊過 ⇒ 這裡通常已是 1000 的倍數、不再改動。留著當「上層漏對齊」
                    #   的最後防線，並印出**原始**股數（舊版印的是進位後的數字，讀日誌會被誤導）。
                    _asked_qty = int(qty)
                    _aligned = board_lot_qty(_asked_qty)
                    if _aligned <= 0:
                        result_holder["error"] = "quantity too small for board lot order"
                        return
                    if _aligned != _asked_qty:
                        print(f"↻  {sym} {_asked_qty} 股依整股規則送出 {_aligned} 股"
                              f"（{_aligned // LOT} 張，餘數 >=500 進位、<500 捨去）")
                    qty = _aligned // LOT

                # 下單：失敗時「強制重登 + 重試一次」
                # 根因：login() 內有 `if self._logged_in: return`（no-op），
                #      session 失效時永遠不會重登 → 持續回 A00002: response parse Error
                #      （2026-09-11：3515/2006 連 35 敗、0 成交）。
                _last_err = None
                for _attempt in (1, 2):
                    order = OrderObject(
                        buy_sell=buy_sell,
                        price=price,
                        stock_no=sym,
                        quantity=qty,
                        ap_code=ap_code,
                        bs_flag=BSFlag.ROD,
                        price_flag=PriceFlag.Limit,
                        trade=Trade.Cash,
                        user_def="tw-selfselect",
                    )
                    if ESUN_DEBUG:
                        print(f"🐞 [ESUN_DEBUG] attempt={_attempt} 送出 "
                              f"stock_no={sym} buy_sell={buy_sell} price={price} "
                              f"quantity={qty} ap_code={ap_code} bs_flag={BSFlag.ROD} "
                              f"price_flag={PriceFlag.Limit} trade={Trade.Cash}")
                    try:
                        self.login()
                        result = self._trade_sdk.place_order(order)
                        display_qty = qty * 1000 if ap_code == APCode.Common else qty
                        # 把「實際送單股數」回報給上層記帳（2026-09-23 修）：整股進位/捨去會改動股數，
                        # 帳本若沿用計畫股數（int(額度/現價)）就會與券商庫存不一致。
                        result_holder["sent_qty"] = display_qty
                        print(f"✅ E.Sun 下單成功: {order_type} {act} {sym} {display_qty} 股 @ {price:.2f}")
                        result_holder["result"] = result
                        return
                    except Exception as _e:
                        _last_err = str(_e)
                        if ESUN_DEBUG:
                            import traceback as _tb
                            print(f"🐞 [ESUN_DEBUG] attempt={_attempt} 例外類型={type(_e).__name__} "
                                  f"訊息={_last_err}")
                            _tb.print_exc()
                        if is_non_retryable_order_error(_last_err):
                            # 2026-11-04：時間／盤別錯誤（例：000017 非該盤別盤中或預約時間）
                            # 重登不會改變「現在幾點」⇒ 直接放棄。VM 實例：13:45 停泊單被退
                            # → 強制重登 → 重試 → 再被退一次（log 的 ⚠️／❌ 成對就是這樣來的）。
                            print(f"⛔ E.Sun 下單被拒（{_last_err}）→ 時間／盤別錯誤，"
                                  f"重登重試無效，放棄本筆")
                            break
                        if _attempt == 1:
                            print(f"⚠️ E.Sun 下單失敗（{_last_err}）→ 強制重登後重試一次")
                            try:
                                self.force_relogin()
                            except Exception as _re:
                                print(f"⚠️ 強制重登失敗: {_re}")
                            time.sleep(1)
                print(f"❌ E.Sun 下單失敗: {_last_err}")
                result_holder["error"] = _last_err
            except Exception as e:
                print(f"❌ E.Sun 下單失敗: {e}")
                result_holder["error"] = str(e)

        t = threading.Thread(target=_do_place, args=(symbol, action, quantity), daemon=True)
        t.start()
        t.join(timeout=PLACE_ORDER_TIMEOUT)
        if t.is_alive():
            print(f"⚠️ E.Sun 下單逾 {PLACE_ORDER_TIMEOUT} 秒無回應（{symbol} {action} {quantity} 股），已跳過避免主程式凍結")
            # `unknown=True`（2026-10-19）：這裡只是**主程式不等了**，上面的下單執行緒仍在跑、
            # 稍後可能真的在券商成交（當天 8046 就印了「下單成功」）。上層必須把它當「結果未明」
            # 落地追蹤（core.live_utils.record_unknown_order），否則帳上 0 股、隔天補足會買成 2 倍。
            return {"error": f"E.Sun place_order timeout ({PLACE_ORDER_TIMEOUT}s)",
                    "unknown": True, "sent_qty": quantity}
        if "error" in result_holder:
            return {"error": result_holder["error"]}
        # 回傳值 ＝ 券商原始回報（保持原介面：上層會讀 `order_no` 等欄位）＋ 額外帶上
        # `sent_qty` ＝ **實際送單股數**（2026-09-23 修：整股進位/捨去會改動股數，
        # 帳本若沿用計畫股數就會與券商庫存不一致 ⇒ 上層用 `reconcile_order_qty()` 讀這個值）。
        res = result_holder.get("result")
        qty_sent = result_holder.get("sent_qty", quantity)
        px_sent = result_holder.get("sent_price")
        if isinstance(res, dict):
            out = dict(res)
            out["sent_qty"] = qty_sent
            if px_sent is not None:
                out["sent_price"] = px_sent
            return out
        out = {"result": res, "sent_qty": qty_sent}
        if px_sent is not None:
            out["sent_price"] = px_sent
        return out

    # ── 唯讀對帳查詢（2026-09-23；`cairn/environment-scope.md` 要求真錢上線前用券商庫存對帳）──
    def query_inventories(self):
        """券商**庫存**（唯讀）。回傳 SDK 原始 list；失敗/未登入回 `None`。

        ⚠️ 玉山回傳值有單位陷阱（2026-09-23 實測）：
          · 整股列（`ap_code` 為空）：`qty_b`／`cost_sum` 是「股／元」
            （2884 → `qty_b=2000`, `price_avg=45.45`, `cost_sum=-91029`）。
          · 盤中零股列（`ap_code='5'`）：`stk_dats` 是**以 1 股為單位**
            （2881 → `qty=1`, `pay_n=-154` ＝ 153 元 ＋ 1 元手續費），總股數看 `qty_b`（470）。
        ⇒ **取股數一律用 `qty_b`**，不要拿 `stk_dats[].qty` 當總數。
        """
        try:
            self.login()
        except Exception as e:
            print(f"⚠️ query_inventories 登入失敗: {e}")
        if self._trade_sdk is None:
            print("⚠️ query_inventories：trade SDK 不可用（未登入）")
            return None
        try:
            return self._trade_sdk.get_inventories()
        except Exception as e:
            print(f"⚠️ query_inventories 失敗: {type(e).__name__}: {e}")
            return None

    def query_settlements(self):
        """**未交割明細**（唯讀）。回傳 SDK 原始 list；失敗/未登入回 `None`。

        ⚠️ 2026-11-05 實測（模擬環境）：只回**還沒交割**的義務（例：11/05 賣出、11/09 交割、價金 113,496）。
        **交割日一到就從清單消失** ⇒ 它不能拿來回溯歷史買賣（11/03 的買進當天交割完就查不到了），
        但可以看出「接下來幾天還要交割多少錢」——真錢上線前用它確認現金流，比 `get_balance`（模擬帳全 0）可靠。
        """
        try:
            self.login()
        except Exception as e:
            print(f"⚠️ query_settlements 登入失敗: {e}")
        if self._trade_sdk is None:
            print("⚠️ query_settlements：trade SDK 不可用（未登入）")
            return None
        try:
            return self._trade_sdk.get_settlements()
        except Exception as e:
            print(f"⚠️ query_settlements 失敗: {type(e).__name__}: {e}")
            return None

    def query_transactions(self, start=None, end=None):
        """**成交回報**（唯讀，預設今天）。回傳 SDK 原始 list；失敗回 `None`。"""
        today = datetime.now().strftime("%Y-%m-%d")
        start = start or today
        end = end or start
        try:
            self.login()
        except Exception as e:
            print(f"⚠️ query_transactions 登入失敗: {e}")
        if self._trade_sdk is None:
            print("⚠️ query_transactions：trade SDK 不可用（未登入）")
            return None
        try:
            return self._trade_sdk.get_transactions_by_date(start, end)
        except Exception as e:
            print(f"⚠️ query_transactions 失敗: {type(e).__name__}: {e}")
            return None

    def check_fill(self, symbol, action, order_ret, requested):
        """查詢今日成交回報，回傳實際成交股數（0=未成交）。

        成交資料格式不明時回傳 None（維持原行為視為全成交，避免誤判少買）。
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            txs = self._trade_sdk.get_transactions_by_date(today, today)
            if txs is None:
                return None
            total = 0
            parsed_any = False
            for tx in txs:
                d = tx if isinstance(tx, dict) else {}
                sid = d.get("stock_no") if isinstance(tx, dict) else getattr(tx, "stock_no", None)
                if sid is None:
                    return None
                parsed_any = True
                if str(sid).strip() != str(symbol).strip():
                    continue
                qty = d.get("match_quantity") if isinstance(tx, dict) else getattr(tx, "match_quantity", None)
                if qty is None:
                    qty = d.get("quantity") if isinstance(tx, dict) else getattr(tx, "quantity", None)
                if qty is None:
                    return None
                total += int(qty)
            return total if parsed_any else None
        except Exception as e:
            print(f"⚠️ E.Sun 成交查詢失敗: {e}")
            return None
