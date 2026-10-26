# Project Cairn Log

本檔以倒序記錄實質推進（最新在最上面，緊接這行之下）。每則保持精簡——只寫摘要與指標，結論沉澱到 `cairn/<主題>.md`。

## 2026-10-26 · 重建 cairn 知識層，補回 4 份被引用卻不存在的檔案

- 現況：repo 有 7 處程式註解、教材腳本引用 `cairn/total-assets-reconciliation.md`、`cairn/environment-scope.md`、`cairn/LOG.md`、`cairn/backtest-data-pitfalls.md` 與 `AGENTS.md`，但這 5 個檔案在檔案系統與 git 歷史中都不存在 ⇒ 死連結。
- 處置：以 `selective_migrate` 從程式註解與腳本 docstring 反推 3 份知識專題文件，並建立規則入口。
- 影響：7 處既有引用全部轉為有效連結，程式碼不需要修改。
- 指標：`cairn/total-assets-reconciliation.md`、`cairn/environment-scope.md`、`cairn/backtest-data-pitfalls.md`、`AGENTS.md`。

## 2026-10-26 · Project Cairn 初始化

- 建立 Project Cairn 結構。
- 歷史知識策略：`selective_migrate`（既有註解與 docstring 中的事故知識搬進知識專題文件；其餘既有文件不動）。
- `cairn/` 政策：`track`（進版控，避免知識層再度無聲消失）。
- 畢業 provider：暫緩對接。
- 細節：見 `AGENTS.md` 與 `.cairn/config.yaml`。
