# plans/ppt — 教學投影片（W1–W6，講稿版）

從母專案 [tw-autotrader](https://github.com/dinchentech/tw-autotrader) 的
`plans/ppt/TW-AUTOTRADER台股買賣自動化系統-W*-講稿版.pptx` 複製改寫而來，
改成 **tw-selfselect（自選股／每月換股單一資金腿）** 的內容。

> 只複製「講稿版」（含逐頁講稿備註）。母專案另有「原版」與「配音版」（內嵌旁白音檔），
> 配音版沒有複製——旁白已錄好，改文字會跟聲音對不上。

## 相對母檔的變更

| 項目 | 說明 |
|---|---|
| 品牌 | 檔名與標題頁 `TW-AUTOTRADER` → `TW-SELFSELECT` |
| 刪頁（W4） | 23–33（全輪替策略、季度排程、ROTATE_MODE 自動化流程、法人抬轎動能、Group 2）、36（全輪替回測）、38（為什麼大資金不適合全輪替） |
| 刪頁（W6） | 20（「每季選股為何勝 0050」——整頁都是全輪替論述）|
| 表格列刪除 | W4 風險控制頁移除 Group 2 欄；W6 策略選擇建議表移除法人動能、全輪替兩列 |
| 文字改寫 | W1 六大策略→五大策略；W2 掛載用途與 DEBUG 範例去 ROTATE_；W3 法人動能案例改為通用舊回測；W4 策略清單 6→5；W5 回測模式五（法人抬轎）移除；W6 策略備註、持股數目講稿去全輪替 |
| W4「法人確認濾網」頁 | 表格改寫成 tw-selfselect 口徑（15 日法人淨買超、TWSE T86 自動補抓／pass-through、`--no-inst`／`--inst-days`），刪掉全輪替的回測數字列 |
| 全域替換 | `live_trader_multi.py` → `selfselect_trader.py`；`ROTATE_MODE_VAL` → 通用變數示例 |

驗證：轉換後六個檔以 python-pptx 重新開啟無誤，全文（含講稿備註、表格）掃描
`全輪替｜法人動能｜法人抬轎｜ROTATE_｜live_trader_multi｜TW-AUTOTRADER` 皆 0 命中；
W4/W6 以 LibreOffice 轉 PDF 抽頁目視確認版面正常（頁碼是自動欄位，刪頁後會自己重編）。

## 檔案

| 檔案 | 頁數 |
|---|---|
| `TW-SELFSELECT台股買賣自動化系統-W1-講稿版.pptx` | 17 |
| `TW-SELFSELECT台股買賣自動化系統-W2-講稿版.pptx` | 28 |
| `TW-SELFSELECT台股買賣自動化系統-W3-講稿版.pptx` | 24 |
| `TW-SELFSELECT台股買賣自動化系統-W4-講稿版.pptx` | 26（原 39）|
| `TW-SELFSELECT台股買賣自動化系統-W5-講稿版.pptx` | 26 |
| `TW-SELFSELECT台股買賣自動化系統-W6-講稿版.pptx` | 20（原 21）|
