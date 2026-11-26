"""
大盤年線（MA200）過濾器
資料源：TWSE 公開 API（FMTQIK），免 token、免套件
抓不到時安全跳過（不過濾）

用法：
    filter = MarketTrendFilter()
    if filter.is_above_ma200():
        # 可以買進
"""
import os
import pandas as pd
from datetime import datetime, timedelta

class MarketTrendFilter:
    def __init__(self):
        self.cache = None
        self.cache_date = None
        # 2026-11-24（v1.1.48）：日 K 序列與即時指數各自快取——
        #   日 K 一天抓一次就好（MA200 盤中不會變）；即時指數 60 秒 TTL。
        self._df = None
        self._df_date = None
        self._live_price = 0.0
        self._live_ts = 0.0
        # 2026-11-24（v1.1.49）：停泊閘門每圈被呼叫 2 次（C＋A）⇒ 診斷行每天只印第一次。
        self._live_log_date = None
    
    def is_above_ma200(self) -> bool:
        """回傳 True = 指數在年線之上（可以買），False = 指數跌破年線（跳過買進）

        2026-11-23：宣告答案**按日快取**（`self.cache`／`self.cache_date` 從 2026-09 就宣告了但一直是死碼）。
        原因：停泊的 A 閘門（`core.park_asset.market_filter_on()`）在 13:25–13:30 每 60 秒問一次，
        每次會抓 15 次 TWSE（約 200+ 筆）⇒ 一天多出近百次外部請求；快取後同一交易日只問一次。
        """
        today = datetime.now().strftime("%Y%m%d")
        if self.cache is not None and self.cache_date == today:
            return bool(self.cache)
        try:
            ma200, last_close = self._ma200_and_last()
            if ma200 is None:
                return self._remember(today, True)
            above = bool(last_close > ma200)
            if above:
                print(f"📈 大盤過濾：指數 {last_close:.0f} > MA200 {ma200:.0f}，允許買進")
            else:
                print(f"📉 大盤過濾：指數 {last_close:.0f} < MA200 {ma200:.0f}，跳過買進")
            return self._remember(today, above)
        except Exception as e:
            print(f"⚠️  大盤過濾異常 ({e})，跳過過濾")
            return self._remember(today, True)

    def _log_live_once(self, msg: str) -> None:
        """停泊閘門的診斷行**每天只印一次**（13:25–13:30 每 60 秒一圈 × C/A 兩處呼叫會洗版）。

        與 v1.1.43 的 `🅿️ 停泊額度 …` 去重同一個理由：真正的異常會被重複行擠出 `docker logs --tail`。
        隔天會再印（跨日重置）；行程重啟最多多印一次（不必落檔）。
        """
        today = datetime.now().strftime("%Y%m%d")
        if self._live_log_date == today:
            return
        self._live_log_date = today
        print(msg)

    def _ma200_and_last(self):
        """回傳 `(MA200, 最後一個日 K 收盤)`；日 K 不足 200 筆回 `(None, None)`。

        日 K 序列**按日快取**（MA200 盤中不變，沒必要每圈重抓 15 次 TWSE）。
        """
        today = datetime.now().strftime("%Y%m%d")
        if not (self._df is not None and self._df_date == today):
            self._df = self._fetch_tw_index()
            self._df_date = today
        df = self._df
        if df is None or len(df) < 200:
            print("⚠️  大盤過濾：資料不足 200 筆，跳過過濾")
            return (None, None)
        close = df['close']
        return (float(close.rolling(200).mean().iloc[-1]), float(close.iloc[-1]))

    def index_now(self, ttl: float = 60.0, stale_ok: float = 1800.0) -> float:
        """TWSE MIS 即時加權指數（`t00`）。60 秒內用快取；取不到就退回**當天最後一個即時值**
        （≤30 分鐘，`stale_ok`）；連那個都沒有才回 `0.0`（＝未知）。

        ⚠️ 2026-11-25 事故（v1.1.51）：舊版取不到就直接回 0，呼叫端退回「日K收盤」——
        而日K收盤是**前一日**的收盤。11/25 13:30 那圈 MIS 掛掉 ⇒ 退回 11/24 的 40,1xx（在年線上）
        ⇒ A 閘門瞬間翻成「可停泊」⇒ 同一窗口把剛釋出的停泊買回去（見 `is_above_ma200_live` 的說明）。
        現在失敗時優先用「今天稍早的即時值」；真的沒有今天任何即時值 ⇒ 回 0.0 = 未知，
        由呼叫端決定「不動作」，**不得**拿昨收當今天。
        """
        import time as _time
        now = _time.time()
        if self._live_price > 0 and (now - self._live_ts) < ttl:
            return self._live_price
        px = 0.0
        try:
            from core.inst_data import fetch_intraday_quotes
            q = fetch_intraday_quotes(['t00'], timeout=6, allow_prev_close=False)
            px = float(((q or {}).get('t00') or {}).get('price') or 0.0)
        except Exception:
            px = 0.0
        if px > 0:
            self._live_price, self._live_ts = px, now
            return px
        if self._live_price > 0 and (now - self._live_ts) <= stale_ok:
            return self._live_price
        return 0.0

    def is_above_ma200_live(self):
        """**停泊閘門（A/C）專用**：MA200 用日 K、現值用**當日即時指數**（2026-11-24 使用者裁定）。

        回傳 `True`／`False`／**`None`（今天沒有任何即時指數＝未知 ⇒ 呼叫端不動作）**。

        為什麼要這一版：A/C 原本跟自選股買進共用 `is_above_ma200()`（看**前一日收盤**），
        遇到跳空日會慢一天——2026-11-24 實例：台股 +9.0%、0050 漲停 95.70，但 13:25 的 A/C
        只看到 11/23 收盤 36,811（< MA200 38,984）⇒ 把停泊賣在漲停、隔天再買回。
        改成「日 K MA200 × 即時指數」後，同一情境就不會賣出停泊。

        取不到即時指數（MIS 掛掉／非交易時段）⇒ **退回日 K 收盤**（＝舊行為），不擋停泊。
        ⚠️ 自選股買進仍然走 `is_above_ma200()`（日 K，與回測同口徑）——這裡刻意只改停泊。
        """
        try:
            ma200, last_close = self._ma200_and_last()
            if ma200 is None:
                return True
            live = self.index_now()
            if live <= 0:
                # 2026-11-25（v1.1.51）：回 **None＝未知**（不再退回昨收、不得翻轉閘門）。
                self._log_live_once(f"⚠️  大盤過濾（停泊）：今天取不到任何即時指數 ⇒ 本次不動作（保守留現金）")
                return None
            above = bool(live > ma200)
            self._log_live_once(f"{'📈' if above else '📉'} 大盤過濾（停泊·即時）：指數 {live:.0f} "
                                f"{'>' if above else '<'} MA200 {ma200:.0f}，"
                                f"{'可停泊' if above else '留現金'}")
            return above
        except Exception as e:
            print(f"⚠️  大盤過濾（停泊）異常 ({e})，跳過過濾")
            return True

    def _remember(self, day: str, value: bool) -> bool:
        self.cache = bool(value)
        self.cache_date = day
        return bool(value)
    
    def _fetch_tw_index(self):
        """從 TWSE 公開 API 抓取加權指數日線（免 token、免套件）
        
        一次只回傳約一個月資料，自動往前翻頁直到湊足 200+ 筆。
        """
        today = datetime.now()
        all_rows = []
        seen_dates = set()
        
        # 往前翻 15 次（約 15 個月），每次倒退 40 天
        for i in range(15):
            d = today - timedelta(days=i * 40)
            dt = d.strftime("%Y%m%d")
            try:
                import requests
                url = "https://www.twse.com.tw/en/exchangeReport/FMTQIK"
                params = {"response": "json", "date": dt}
                resp = requests.get(url, params=params, headers={
                    "User-Agent": "Mozilla/5.0",
                }, timeout=10)
                data = resp.json()
                for row in data.get("data", []):
                    if row[0] not in seen_dates:
                        seen_dates.add(row[0])
                        all_rows.append(row)
                if len(all_rows) >= 200:
                    break
            except Exception as e:
                print(f"⚠️  大盤過濾：TWSE 第 {i+1} 次抓取失敗 ({e})")
                continue
        
        if len(all_rows) >= 200:
            df = pd.DataFrame(all_rows, columns=[
                "date", "volume", "value", "trades", "TAIEX", "change"
            ])
            df["close"] = pd.to_numeric(
                df["TAIEX"].str.replace(",", ""), errors="coerce"
            )
            df = df.dropna(subset=["close"])
            df = df.sort_values("date")
            print(f"✅ 大盤過濾：成功取得 TWSE 加權指數 ({len(df)} 筆)")
            return df
        else:
            print(f"⚠️  大盤過濾：TWSE 僅回傳 {len(all_rows)} 筆，不足 200")
        
        return None
