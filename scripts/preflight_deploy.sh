#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 部署前檢查（pre-flight）：跑測試，失敗就**不要部署**
#
#   scripts/preflight_deploy.sh          # 由 deploy_source.sh 自動呼叫
#   SKIP_PREFLIGHT=1 ./deploy_source.sh  # 急修時可跳過（不建議）
#
# 為什麼要有這支（2026-10-02 事故）：
#   v4.41 部署了一個「啟動即崩」的版本（`UnboundLocalError: selection_window_open`），
#   容器進入**無限重啟**（RestartCount=25）、當天整個交易時段沒跑、TG 被啟動訊息洗版。
#   那種錯誤其實已經有守門測試（AST 掃「綁定前使用」）—— 但**沒人先跑**。
#   所以把「跑測試」變成部署流程的**前置步驟**：紅燈就中止，不 build、不上傳、不動 VM。
#
# 設計要點：
#   - 測試期間**清掉 TG/LINE token**（`env -u`）：測試會走到通知路徑，
#     帶著真 token 跑會在使用者手機上刷一排「測試訊息」。
#   - 用「命令替換 + `||`」拿 python 的真實 exit code，**不要** `cmd | tail`
#     （管線的 exit code 是最後一個指令，會把失敗吃掉）。
# ══════════════════════════════════════════════════════════════
set -uo pipefail

START_DIR="${PREFLIGHT_START_DIR:-test}"
PATTERN="${PREFLIGHT_PATTERN:-test_*.py}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

if [ -x .venv/bin/python ]; then
  PY=".venv/bin/python"
else
  PY="$(command -v python3 || command -v python)"
fi
[ -n "$PY" ] || { echo "❌ 找不到 python 直譯器"; exit 1; }

echo "🧪 部署前檢查：$PY -m unittest discover -s $START_DIR -p '$PATTERN'"
echo "   （已清掉 TELEGRAM_BOT_TOKEN／TELEGRAM_CHAT_ID／LINE_NOTIFY_TOKEN ⇒ 測試不會真的發通知）"

OUT="$(env -u TELEGRAM_BOT_TOKEN -u TELEGRAM_CHAT_ID -u LINE_NOTIFY_TOKEN \
        "$PY" -m unittest discover -s "$START_DIR" -p "$PATTERN" 2>&1)"
RC=$?

echo "$OUT" | tail -3
if [ "$RC" -ne 0 ]; then
  echo ""
  echo "── 失敗細節（完整輸出；部署前檢查就是為了在這裡擋下來）──"
  echo "$OUT"
  echo ""
  echo "❌ 部署前檢查失敗（unittest exit=${RC}）⇒ 中止部署。"
  echo "   ℹ️ 真的要跳過：SKIP_PREFLIGHT=1 ./deploy_source.sh（只建議用於與程式無關的急修）"
  exit 1
fi
echo "✅ 部署前檢查通過"
