#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# 把 VM 上產生的儀表板推到 GitHub Pages（docs/index.html）
#
#   /usr/local/bin/publish_dashboard.sh          # 由 cron（台北 13:50、週一至五）呼叫
#   DRY_RUN=1 ./publish_dashboard.sh             # 只比對不 push
#
# 為什麼要這支（2026-10-27 使用者指定）：
#    儀表板由 selfselect_trader.py 在台北 13:45 產生（logs/dashboard.html），
#    但 GitHub Pages 站台只認 repo 裡 docs/index.html，而且 pages.yml 只在
#    「push 到 main 且改到 docs/」時才部署 ⇒ 沒有這支，公開頁永遠停在手動更新那天。
#
# 機制：VM 的 ~/tw-selfselect 沒有 .git（deploy_source.sh 是 scp 上傳），
#    所以另外用一個**只取 docs/ 的 sparse clone**（~ /dash-publish）當發佈工作區，
#    每次執行都 reset 到 origin/main 再覆蓋檔案、commit、push。
#
# ⚠️ 公開性：**要不要公開由使用者決定**，開關是 `.env` 的 `DASHBOARD_PUBLISH`
#    （預設 0＝不公開；設 1 才會推）。完整儀表板含持股股數、平均成本、總資產，
#    推到公開 Pages ⇒ 全世界可見。模擬帳無妨，**切 ESUN_ENVIRONMENT=real 前要重新評估**。
#
# 憑證（二選一，優先 deploy key）：
#   1. **deploy key（推薦，不會過期）**：~/.dash-deploy-key（ed25519, chmod 600）
#      ＋ GitHub repo → Settings → Deploy keys → 貼上 .pub、勾「Allow write access」。
#      走 SSH（git@github.com:<repo>.git），不需要 token。
#   2. fine-grained PAT：~/ .dash-publish-token（chmod 600）內放
#      token（只給 dinchentech/tw-selfselect，權限 Contents: Read and write）。
#      token 不寫進 remote URL，改用 http.extraheader 傳 Authorization，避免留在 .git/config。
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

SRC="${DASH_SRC:-$HOME/tw-selfselect/logs/dashboard.html}"
CLONE="${CLONE_DIR:-$HOME/dash-publish}"
TOKEN_FILE="${TOKEN_FILE:-$HOME/.dash-publish-token}"
DEPLOY_KEY="${DEPLOY_KEY:-$HOME/.dash-deploy-key}"
REPO_SLUG="${REPO_SLUG:-dinchentech/tw-selfselect}"
BRANCH="${BRANCH:-main}"
REMOTE_URL="https://github.com/${REPO_SLUG}.git"
LOG="${DASH_LOG:-$HOME/tw-selfselect/logs/publish_dashboard.log}"
ENV_FILE="${ENV_FILE:-$HOME/tw-selfselect/.env}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "$(dirname "$LOG")" 2>/dev/null
say() { echo "$(TZ=Asia/Taipei date '+%F %T') $*" >> "$LOG" 2>/dev/null; }

notify() {   # 只在失敗時吵人（成功不發，避免每天一則）
  [ -f "$ENV_FILE" ] || return 0
  local tk ch
  tk=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d ' ')
  ch=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d ' ')
  [ -n "$tk" ] && [ -n "$ch" ] || return 0
  curl -s -X POST "https://api.telegram.org/bot${tk}/sendMessage" \
    --data-urlencode "chat_id=${ch}" --data-urlencode "text=$1" >/dev/null 2>&1
}

fail() { say "❌ $*"; notify "⚠️ TW SelfSelect 儀表板發佈失敗：$*"; exit 1; }

# ── 前置檢查 ─────────────────────────────────────────────────────────
# 總開關 `DASHBOARD_PUBLISH`（預設 0＝不公開）。公開與否是使用者的決定，
# 不該因為裝了 cron 就默默把持股與總資產推上網。
PUBLISH="${DASHBOARD_PUBLISH:-}"
if [ -z "$PUBLISH" ] && [ -f "$ENV_FILE" ]; then
  PUBLISH=$(grep -E '^DASHBOARD_PUBLISH=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"' | tr -d ' ')
  PUBLISH="${PUBLISH%%#*}"; PUBLISH=$(echo "$PUBLISH" | tr -d ' ')
fi
case "${PUBLISH:-0}" in
  1|true|TRUE|on|ON|yes|YES) ;;
  *) say "⏭ DASHBOARD_PUBLISH=${PUBLISH:-未設定}（需為 1）⇒ 依設定不公開儀表板"; exit 0 ;;
esac

# ── 憑證：deploy key 優先，其次 PAT ──────────────────────────────────
AUTH_ARGS=()
CLONE_URL=""
if [ -s "$DEPLOY_KEY" ]; then
  chmod 600 "$DEPLOY_KEY" 2>/dev/null || true
  export GIT_SSH_COMMAND="ssh -i ${DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=${HOME}/.ssh/known_hosts"
  mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh" 2>/dev/null || true
  REMOTE_URL="git@github.com:${REPO_SLUG}.git"
  CLONE_URL="$REMOTE_URL"
  AUTH_MODE="deploy-key"
  say "🔑 憑證：deploy key（${DEPLOY_KEY}）"
else
  [ -f "$TOKEN_FILE" ] || { say "⏭ 沒有 ${DEPLOY_KEY}（deploy key）也沒有 $TOKEN_FILE（PAT）⇒ 跳過"; exit 0; }
  TOKEN=$(tr -d ' \r\n' < "$TOKEN_FILE")
  [ -n "$TOKEN" ] || { say "⏭ PAT 檔為空、也沒有 deploy key ⇒ 跳過"; exit 0; }
  REMOTE_URL="https://github.com/${REPO_SLUG}.git"
  CLONE_URL="https://x-access-token:${TOKEN}@github.com/${REPO_SLUG}.git"
  AUTH_HEADER="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$TOKEN" | base64 | tr -d '\n')"
  AUTH_ARGS=(-c "http.extraheader=${AUTH_HEADER}")
  AUTH_MODE="pat"
  say "🔑 憑證：fine-grained PAT（${TOKEN_FILE}）"
fi

[ -f "$SRC" ] || { say "⏭ 找不到儀表板 $SRC（13:45 才會產生）⇒ 跳過"; exit 0; }

SRC_DATE=$(TZ=Asia/Taipei date -d "@$(stat -c %Y "$SRC")" '+%F')
TODAY=$(TZ=Asia/Taipei date '+%F')
[ "$SRC_DATE" = "$TODAY" ] || { say "⏭ 儀表板是 $SRC_DATE 的（非今日 $TODAY）⇒ 跳過"; exit 0; }

# ── 準備工作區（只取 docs/ 的 sparse clone）──────────────────────────
if [ ! -d "$CLONE/.git" ]; then
  say "📦 建立 sparse clone：$CLONE"
  git clone --depth 1 --filter=blob:none --sparse \
    "$CLONE_URL" "$CLONE" >>"$LOG" 2>&1 \
    || fail "clone 失敗（檢查憑證與網路）"
  ( cd "$CLONE" && git sparse-checkout set docs >>"$LOG" 2>&1 ) || fail "sparse-checkout 失敗"
fi

cd "$CLONE" || fail "無法進入 $CLONE"

# 每次都跟 origin 對齊（工作區是拋棄式的，沒有本地修改要保留）
git remote set-url origin "$REMOTE_URL" >>"$LOG" 2>&1
git "${AUTH_ARGS[@]}" fetch --depth 1 origin "$BRANCH" >>"$LOG" 2>&1 \
  || fail "fetch 失敗（憑證失效或沒有 Contents 寫入權限？mode=${AUTH_MODE}）"
git reset --hard "origin/$BRANCH" >>"$LOG" 2>&1 || fail "reset 失敗"

cp "$SRC" "$CLONE/docs/index.html" || fail "複製儀表板失敗"
git add docs/index.html
if git diff --cached --quiet; then
  say "⏭ 儀表板內容與線上相同 ⇒ 不用發佈"
  exit 0
fi

if [ "$DRY_RUN" = "1" ]; then
  say "🔎 DRY_RUN：會發佈 $SRC_DATE 的儀表板（$(stat -c %s "$SRC") bytes）"
  git diff --cached --stat >>"$LOG" 2>&1
  exit 0
fi

NOW_HM=$(TZ=Asia/Taipei date '+%H:%M')
# 身分寫死在命令列：cron 環境常常沒有 user.email，沒設會 commit 失敗（2026-10-28 實測 VM 只有 user.name）
GIT_ID=(-c "user.name=${GIT_AUTHOR_NAME:-tw-selfselect-dashboard}" -c "user.email=${GIT_AUTHOR_EMAIL:-dashboard@tw-selfselect.local}")
TZ=Asia/Taipei git "${GIT_ID[@]}" commit -q -F - >>"$LOG" 2>&1 <<MSG || fail "commit 失敗"
儀表板：自動發佈 ${SRC_DATE} 資料

由 VM 的 publish_dashboard.sh 於台北 ${NOW_HM} 產生後推送。
MSG

if git "${AUTH_ARGS[@]}" push origin "HEAD:${BRANCH}" >>"$LOG" 2>&1; then
  say "✅ 已發佈 ${SRC_DATE} 儀表板（$(git rev-parse --short HEAD)，${AUTH_MODE}）"
else
  fail "push 失敗（見 log 尾段）"
fi
