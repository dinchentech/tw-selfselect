#!/bin/bash
# TW SelfSelect 看門狗：每 5 分鐘檢查容器健康 + 清除重複實盤實例
# 由 root crontab 執行（crontab -l 可查看）
CONTAINER_NAME="tw_selfselect_bot"
LOG="/var/log/tw_watchdog.log"
ENV_FILE="/home/frank/tw-selfselect/.env"

TOKEN=""
CHAT_ID=""
if [ -f "$ENV_FILE" ]; then
  TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d ' ')
  CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d ' ')
fi

notify() {
  [ -n "$TOKEN" ] && [ -n "$CHAT_ID" ] || { echo "$(date '+%F %T') 缺少 TELEGRAM_BOT_TOKEN/CHAT_ID，略過通知" >> "$LOG"; return 0; }
  curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${CHAT_ID}" --data-urlencode "text=$1" >/dev/null 2>&1
}

RUNNING=$(docker inspect "$CONTAINER_NAME" --format '{{.State.Running}}' 2>/dev/null)
CONTAINER_PID=$(docker inspect "$CONTAINER_NAME" --format '{{.State.Pid}}' 2>/dev/null)

if [ "$RUNNING" != "true" ]; then
  echo "$(date '+%F %T') 容器未運行 → 嘗試啟動" >> "$LOG"
  docker start "$CONTAINER_NAME" >> "$LOG" 2>&1
  notify "⚠️ TW SelfSelect 容器未運行，已自動重啟（watchdog）"
  exit 0
fi

ROGUE=""
for pid in $(pgrep -f "selfselect_trader.py" 2>/dev/null); do
  if [ "$pid" != "$CONTAINER_PID" ]; then
    exe=$(readlink /proc/$pid/exe 2>/dev/null)
    case "$exe" in
      *python*) ;;              # 只處理真正的 python 實例
      *) continue ;;            # shell/grep 等誤匹配（如 ps 指令）跳過
    esac
    info=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null)
    kill -9 "$pid" 2>/dev/null
    ROGUE="${ROGUE} ${pid}[${info}]"
  fi
done

if [ -n "$ROGUE" ]; then
  echo "$(date '+%F %T') 清除重複實例:${ROGUE}" >> "$LOG"
  notify "⚠️ TW SelfSelect 清除重複實盤實例:${ROGUE}"
fi
