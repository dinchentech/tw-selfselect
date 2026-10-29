#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# 安裝「儀表板自動發佈」到 VM：來源 scripts/vm/publish_dashboard.sh
#
#   ./scripts/vm/install_dashboard_publish.sh              # 安裝腳本 + cron
#   ./scripts/vm/install_dashboard_publish.sh --no-cron    # 只裝腳本（先測試用）
#   VERIFY_ONLY=1 ./scripts/vm/install_dashboard_publish.sh
#
# 前置（二選一）：
#   1. **deploy key（推薦，不會過期）**：VM 上 ~/.dash-deploy-key（ed25519, 600），
#      公鑰貼到 GitHub repo → Settings → Deploy keys（勾 Allow write access）。
#   2. fine-grained PAT：VM 上 ~/.dash-publish-token（600），權限 Contents: Read and write。
#   兩者都沒有時本腳本會「裝好但不加 cron」，並印出建立步驟（避免每天空跑留 log）。
#
# 排程：台北 13:50、週一至五（cron 用系統時區 = UTC ⇒ 50 5 * * 1-5）
#   儀表板在 13:45 產生，14:00 VM 由 GCP 排程關機 ⇒ 13:50 這段是唯一安全窗。
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
SRC="$PWD/publish_dashboard.sh"

VM_NAME="${1:-tw-autotrader}"
ZONE="${2:-asia-east1-b}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"
NO_CRON="${NO_CRON:-0}"
for a in "$@"; do [ "$a" = "--no-cron" ] && NO_CRON=1; done

SSH_OPTS=(--zone="${ZONE}" --quiet --ssh-flag=-o --ssh-flag=ServerAliveInterval=60)
remote() { gcloud compute ssh "${VM_NAME}" "${SSH_OPTS[@]}" --command="$1"; }
scp_to() { gcloud compute scp "$1" "${VM_NAME}:$2" --zone="${ZONE}" --quiet; }

die() { echo ""; echo "❌ $*"; exit 1; }

[ -f "$SRC" ] || die "找不到 $SRC"
bash -n "$SRC" || die "publish_dashboard.sh 語法錯誤"

echo "════════════════════════════════════════════════════════════════════"
echo " 儀表板自動發佈 → ${VM_NAME}（${ZONE}）"
echo "════════════════════════════════════════════════════════════════════"

if [ "$VERIFY_ONLY" = "1" ]; then
  remote 'echo "--- 腳本 ---"; ls -l /usr/local/bin/publish_dashboard.sh 2>/dev/null || echo "未安裝"
          echo "--- 開關 DASHBOARD_PUBLISH ---"
          v=$(grep -E "^DASHBOARD_PUBLISH=" "$HOME/tw-selfselect/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d " " | sed "s/#.*//")
          case "${v:-0}" in 1|true|on|yes) echo "  =${v} ⇒ 會公開";; *) echo "  ${v:-未設定} ⇒ 不公開（要公開請設 1）";; esac
          echo "--- 憑證 ---"
          if [ -s "$HOME/.dash-deploy-key" ]; then stat -c "%a %n" "$HOME/.dash-deploy-key"; echo "  公鑰（要貼到 GitHub Deploy keys）："; cat "$HOME/.dash-deploy-key.pub"; fi
          [ -s "$HOME/.dash-publish-token" ] && stat -c "%a %n（PAT）" "$HOME/.dash-publish-token" || true
          [ -s "$HOME/.dash-deploy-key" ] || [ -s "$HOME/.dash-publish-token" ] || echo "缺少 ~/.dash-deploy-key（推薦）與 ~/.dash-publish-token"
          echo "--- clone ---"; [ -d "$HOME/dash-publish/.git" ] && (cd "$HOME/dash-publish" && git log --oneline -1) || echo "尚未建立 ~/dash-publish"
          echo "--- cron ---"; cat /etc/cron.d/publish_dashboard 2>/dev/null | grep -v "^#" || echo "未加 cron"'
  exit 0
fi

echo "🔑 檢查 GCP 認證..."
gcloud auth print-identity-token &>/dev/null || die "GCP 認證過期：先跑 \`gcloud auth login\`"

echo "📤 上傳腳本..."
scp_to "$SRC" "/tmp/publish_dashboard.sh" || die "上傳失敗"

echo "🧰 VM 端安裝..."
remote 'sudo install -m 755 -o root -g root /tmp/publish_dashboard.sh /usr/local/bin/publish_dashboard.sh && rm -f /tmp/publish_dashboard.sh && echo "   ✓ /usr/local/bin/publish_dashboard.sh"' || die "安裝失敗"

# token 檢查（在 VM 上以 frank 身份判斷）
HAS_CRED=$(remote 'if [ -s "$HOME/.dash-deploy-key" ] || [ -s "$HOME/.dash-publish-token" ]; then echo yes; else echo no; fi' | tr -d "\r" | tail -1)

if [ "$HAS_CRED" != "yes" ]; then
  echo ""
  echo "⚠️  VM 上還沒有憑證（deploy key 或 PAT）⇒ 先不裝 cron（避免每天空跑留 log）"
  echo ""
  echo "方法 A（推薦，不會過期）：deploy key"
  echo "  1) 在 VM 產生金鑰（已存在會沿用）："
  echo "     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='[ -s ~/.dash-deploy-key ] || ssh-keygen -t ed25519 -N \"\" -C \"tw-selfselect-dashboard-deploy\" -f ~/.dash-deploy-key; chmod 600 ~/.dash-deploy-key; cat ~/.dash-deploy-key.pub'"
  echo "  2) 複製上面輸出的公鑰 → GitHub repo → Settings → Deploy keys → Add deploy key（勾 Allow write access）"
  echo "  3) 重跑本腳本（會自動建 sparse clone 並加 cron）：./scripts/vm/install_dashboard_publish.sh"
  echo ""
  echo "方法 B：fine-grained PAT（90 天會過期）"
  echo "  1) GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens"
  echo "     · Repository access：Only select repositories → dinchentech/tw-selfselect"
  echo "     · Permissions → Repository permissions → Contents: Read and write"
  echo "  2) 把 token 貼進 VM（600 權限）："
  echo "     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='umask 077; read -rsp \"PAT: \" T; printf %s \"\$T\" > ~/.dash-publish-token; echo; chmod 600 ~/.dash-publish-token'"
  echo "  3) 重跑本腳本"
  exit 0
fi

echo "   ✓ 憑證已就位"

if [ "$NO_CRON" = "0" ]; then
  remote 'cat <<CRON | sudo tee /etc/cron.d/publish_dashboard >/dev/null
# 儀表板自動發佈（台北 13:50、週一至五）
# ⚠️ cron 用**系統時區**（本機 = UTC）：05:50 UTC = 13:50 台北；14:00 台北 VM 關機。
# 由 scripts/vm/install_dashboard_publish.sh 安裝（勿手改 VM 上的副本）。
50 5 * * 1-5 frank /usr/local/bin/publish_dashboard.sh
CRON
sudo chmod 644 /etc/cron.d/publish_dashboard && echo "   ✓ /etc/cron.d/publish_dashboard"' || die "寫 cron 失敗"
else
  echo "   （--no-cron：略過 cron）"
fi

echo "🔍 試跑一次（DRY_RUN）..."
remote 'DRY_RUN=1 /usr/local/bin/publish_dashboard.sh; echo "exit=$?"; tail -5 "$HOME/tw-selfselect/logs/publish_dashboard.log" 2>/dev/null'

FLAG=$(remote 'v=$(grep -E "^DASHBOARD_PUBLISH=" "$HOME/tw-selfselect/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d " " | sed "s/#.*//"); echo "${v:-0}"' | tr -d "\r" | tail -1)
case "$FLAG" in
  1|true|TRUE|on|ON|yes|YES)
    echo ""
    echo "✅ 完成。台北 13:50 起，每個交易日收盤後會把儀表板推到 GitHub Pages（開關已開）。" ;;
  *)
    echo ""
    echo "✅ 安裝完成，但**開關是關的**（DASHBOARD_PUBLISH=${FLAG:-未設定}）⇒ 排程會跳過、不會公開。"
    echo "   要開始公開：把 VM 的 ~/tw-selfselect/.env 改成 DASHBOARD_PUBLISH=1（主程式對 .env 熱重載，不用重啟）" ;;
esac
echo "   驗證：VERIFY_ONLY=1 ./scripts/vm/install_dashboard_publish.sh"
