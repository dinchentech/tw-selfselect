#!/bin/bash
# ══════════════════════════════════════════════════════════════
# 容器「崩潰迴圈」守門員（在 VM 上由 cron 每 5 分鐘執行）
#
#   /usr/local/bin/tw_restart_guard.sh          # 安裝後由 cron 呼叫
#   DRY_RUN=1 GUARD_STATE=/tmp/x /usr/local/bin/tw_restart_guard.sh
#
# 為什麼要有這支（2026-10-02 事故）：
#   v4.41 部署了一個啟動即崩的版本 ⇒ docker 依 restart policy 每分鐘重啟、
#   每次重啟都送一則啟動 Telegram ⇒ **無聲迴圈 15 小時**（RestartCount=25）、
#   當天整個交易時段沒跑，而且使用者只看到「程式一直重啟」的洗版。
#   現有 `tw_watchdog.sh` 只會「容器沒跑就拉起來」——**正是它讓迴圈一直轉**。
#
# 行為（每 5 分鐘一次）：
#   1. 讀容器的 `StartedAt`：與上次記錄不同 ⇒ 視為一次「重啟」，記進狀態檔。
#   2. 同一視窗內重啟次數 ≥ GUARD_MAX_RESTARTS ⇒
#        ① 發 Telegram（含容器 log 尾段＝**真正的崩潰原因**）
#        ② `docker update --restart=no` 停掉自動重啟（避免無限轉）
#        ③ 標記 PAUSED + 暫停時間
#   3. PAUSED 且已超過 GUARD_RESUME_AFTER_MIN ⇒ 自動恢復 `--restart=unless-stopped`
#        並通知「已恢復」（暫停只是止血，不是永久關機；若又崩會再被擋一次並再通知）
#
# 所有門檻都可用環境變數覆寫（測試就是靠這個注入假 docker／假狀態檔）。
# ══════════════════════════════════════════════════════════════
set -uo pipefail

CONTAINER="${GUARD_CONTAINER:-tw_selfselect_bot}"
STATE="${GUARD_STATE:-/var/lib/tw_selfselect/restart_guard.state}"
LOG="${GUARD_LOG:-/var/log/tw_restart_guard.log}"
ENV_FILE="${GUARD_ENV_FILE:-/home/frank/tw-selfselect/.env}"
MAX_RESTARTS="${GUARD_MAX_RESTARTS:-6}"          # 視窗內允許的重啟次數（超過就擋）
WINDOW_MIN="${GUARD_WINDOW_MIN:-60}"             # 觀察視窗（分鐘）
RESUME_AFTER_MIN="${GUARD_RESUME_AFTER_MIN:-180}" # 暫停後多久自動恢復（分鐘）
ALERT_COOLDOWN_MIN="${GUARD_ALERT_COOLDOWN_MIN:-60}"
ALERT_ONLY="${GUARD_ALERT_ONLY:-0}"              # 1＝只通知、不改 restart policy
DRY_RUN="${DRY_RUN:-0}"
NOW="${GUARD_NOW:-$(date +%s)}"

say() { echo "$(date -d "@${NOW}" '+%F %T') $*" >> "$LOG" 2>/dev/null || echo "$*"; }

notify() {
  # token 一律從 .env 讀（**不留硬編碼 fallback**：舊 watchdog 把 token 寫死在腳本裡，是資安債）
  local token="" chat=""
  if [ -f "$ENV_FILE" ]; then
    token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d ' ')
    chat=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d ' ')
  fi
  if [ -z "$token" ] || [ -z "$chat" ]; then
    say "（未設定 TELEGRAM_BOT_TOKEN/CHAT_ID ⇒ 只寫 log）$1"
    return 0
  fi
  curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    --data-urlencode "chat_id=${chat}" --data-urlencode "text=$1" >/dev/null 2>&1
  say "已發 Telegram：$(echo "$1" | head -1)"
}

docker_field() {  # $1: format
  docker inspect "$CONTAINER" --format "$1" 2>/dev/null
}

mkdir -p "$(dirname "$STATE")" 2>/dev/null
touch "$STATE" 2>/dev/null

STARTED="$(docker_field '{{.State.StartedAt}}')"
if [ -z "$STARTED" ]; then
  say "容器 ${CONTAINER} 不存在或 docker 無回應 ⇒ 略過（不計入重啟）"
  exit 0
fi

# ── 狀態檔格式：每行一個 epoch（重啟時間），另有 `PAUSED <epoch>` 標記 ──
LAST_STARTED="$(grep '^STARTED ' "$STATE" 2>/dev/null | tail -1 | awk '{print $2}')"
PAUSED_AT="$(grep '^PAUSED ' "$STATE" 2>/dev/null | tail -1 | awk '{print $2}')"
LAST_ALERT="$(grep '^ALERTED ' "$STATE" 2>/dev/null | tail -1 | awk '{print $2}')"

if [ "$STARTED" != "$LAST_STARTED" ]; then
  say "偵測到容器啟動（StartedAt=${STARTED}）⇒ 記為一次重啟"
  # ⚠️ 只換掉 STARTED 那一行，**RESTART 歷史必須保留**（那是判斷迴圈的依據）；
  #    2026-10-02 初版把 RESTART 一起濾掉 ⇒ 視窗內永遠只算到 1 次 ⇒ 守門員形同虛設（被測試抓到）。
  { echo "STARTED ${STARTED}";
    grep -v '^STARTED ' "$STATE" 2>/dev/null;
    echo "RESTART ${NOW}"; } > "${STATE}.tmp" && mv "${STATE}.tmp" "$STATE"
fi

CUTOFF=$(( NOW - WINDOW_MIN * 60 ))
RECENT=$(awk -v c="$CUTOFF" '$1=="RESTART" && $2>=c {n++} END {print n+0}' "$STATE" 2>/dev/null)
RECENT=${RECENT:-0}

say "視窗 ${WINDOW_MIN} 分鐘內重啟 ${RECENT} 次（門檻 ${MAX_RESTARTS}）"

# ── 暫停中：時間到就恢復 ─────────────────────────────────────
if [ -n "$PAUSED_AT" ]; then
  ELAPSED=$(( (NOW - PAUSED_AT) / 60 ))
  if [ "$ELAPSED" -ge "$RESUME_AFTER_MIN" ]; then
    if [ "$DRY_RUN" = "1" ]; then
      say "[DRY_RUN] 會恢復 restart policy（已暫停 ${ELAPSED} 分鐘）"
    else
      docker update --restart=unless-stopped "$CONTAINER" >>"$LOG" 2>&1
      grep -v '^PAUSED ' "$STATE" > "${STATE}.tmp" && mv "${STATE}.tmp" "$STATE"
      notify "♻️ TW SelfSelect 容器已恢復自動重啟（先前因崩潰迴圈暫停 ${ELAPSED} 分鐘）"
      say "已恢復 --restart=unless-stopped"
    fi
  else
    say "仍暫停中（已 ${ELAPSED} 分鐘，${RESUME_AFTER_MIN} 分鐘後自動恢復）"
  fi
  exit 0
fi

if [ "$RECENT" -lt "$MAX_RESTARTS" ]; then
  exit 0
fi

COOLDOWN_CUTOFF=$(( NOW - ALERT_COOLDOWN_MIN * 60 ))
if [ -n "$LAST_ALERT" ] && [ "$LAST_ALERT" -ge "$COOLDOWN_CUTOFF" ]; then
  say "已達門檻但仍在通知冷卻期內 ⇒ 不重複通知"
  exit 0
fi

TAIL="$(docker logs --tail 6 "$CONTAINER" 2>&1 | tail -6)"
MSG="🛑 *TW SelfSelect 崩潰迴圈*
容器在 ${WINDOW_MIN} 分鐘內重啟 ${RECENT} 次（門檻 ${MAX_RESTARTS}）
log 尾段：
${TAIL}
$([ "$ALERT_ONLY" = "1" ] && echo '（僅通知模式：未變更 restart policy）' || echo "已停用自動重啟；${RESUME_AFTER_MIN} 分鐘後自動恢復（或人工 docker start）")"
notify "$MSG"

if [ "$ALERT_ONLY" != "1" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    say "[DRY_RUN] 會執行 docker update --restart=no ${CONTAINER}"
  else
    docker update --restart=no "$CONTAINER" >>"$LOG" 2>&1
    echo "PAUSED ${NOW}" >> "$STATE"
    say "已停用自動重啟（避免無限迴圈）"
  fi
fi
echo "ALERTED ${NOW}" >> "$STATE"
say "已發出崩潰迴圈通知（重啟 ${RECENT} 次）"
exit 0
