#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# 安裝／更新 VM 上的三個 root 層守門員（來源都在 scripts/vm/，本檔是唯一安裝入口）
#
#   ./scripts/vm/install_vm_guards.sh                      # 預設 tw-autotrader / asia-east1-b
#   ./scripts/vm/install_vm_guards.sh my-vm asia-east1-b
#   VERIFY_ONLY=1 ./scripts/vm/install_vm_guards.sh        # 只檢查現況，不安裝
#
# 裝什麼（全部 idempotent，重跑不會重複加 cron）：
#   /usr/local/bin/tw_watchdog.sh        ← scripts/vm/tw_watchdog.sh      （root crontab，每 5 分）
#   /usr/local/bin/tw_restart_guard.sh   ← scripts/vm/tw_restart_guard.sh （/etc/cron.d，每 5 分）
#   /usr/local/bin/auto_shutdown.sh      ← scripts/vm/auto_shutdown.sh    （/etc/cron.d，每日 18:00 UTC）
#
# 為什麼要有這支（2026-10-27 事故）：
#   這三支原本只存在 VM 的 /usr/local/bin，repo 內沒有副本。專案從 tw-autotrader
#   拆出、容器改名 tw_selfselect_bot 之後，watchdog 仍盯著 `tw_autotrader_bot`
#   ⇒ 每 5 分鐘發一次「容器未運行」假告警（10-26 收了 115 則、10-27 半天 38 則），
#   而 restart_guard 因為找不到容器一直是「略過」＝崩潰迴圈保護形同失效。
#   ⇒ 來源進 repo、改由本腳本安裝，改名時只要改 scripts/vm/ 下的檔案。
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
SRC_DIR="$PWD"
REPO_ROOT="$(cd "$SRC_DIR/../.." && pwd)"

VM_NAME="${1:-tw-autotrader}"
ZONE="${2:-asia-east1-b}"
VERIFY_ONLY="${VERIFY_ONLY:-0}"

SSH_OPTS=(--zone="${ZONE}" --quiet --ssh-flag=-o --ssh-flag=ServerAliveInterval=60)
remote() { gcloud compute ssh "${VM_NAME}" "${SSH_OPTS[@]}" --command="$1"; }
scp_to() { gcloud compute scp "$1" "${VM_NAME}:$2" --zone="${ZONE}" --quiet; }

die() { echo ""; echo "❌ $*"; exit 1; }

for f in tw_watchdog.sh tw_restart_guard.sh auto_shutdown.sh; do
  [ -f "$SRC_DIR/$f" ] || die "找不到來源檔：$SRC_DIR/$f"
  bash -n "$SRC_DIR/$f" || die "$f 語法錯誤"
done

echo "════════════════════════════════════════════════════════════════════"
echo " VM 守門員 → ${VM_NAME}（${ZONE}）｜來源 ${SRC_DIR#"$REPO_ROOT"/}"
echo "════════════════════════════════════════════════════════════════════"

if [ "$VERIFY_ONLY" = "1" ]; then
  remote 'for f in /usr/local/bin/tw_watchdog.sh /usr/local/bin/tw_restart_guard.sh /usr/local/bin/auto_shutdown.sh; do
            printf "%-45s %s\n" "$f" "$([ -x "$f" ] && stat -c "%y" "$f" || echo "缺少")"; done
          echo "--- root crontab ---"; sudo crontab -l 2>/dev/null | grep -v "^#"
          echo "--- /etc/cron.d ---"; ls /etc/cron.d/ | tr "\n" " "; echo'
  exit 0
fi

echo "🔑 檢查 GCP 認證..."
gcloud auth print-identity-token &>/dev/null || die "GCP 認證過期：先跑 \`gcloud auth login\`"

echo "🖥  檢查 VM..."
STATUS=$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" \
  --format='value(status)' 2>/dev/null | tr -d '\r' | tail -1)
[ "$STATUS" = "RUNNING" ] || die "VM 狀態為 ${STATUS:-未知}，請先開機（排程 08:00 台北）"

echo "📤 上傳來源..."
for f in tw_watchdog.sh tw_restart_guard.sh auto_shutdown.sh; do
  scp_to "$SRC_DIR/$f" "/tmp/$f" || die "上傳 $f 失敗"
done

echo "🧰 VM 端安裝（sudo）..."
remote 'sudo bash -euo pipefail -s' <<'REMOTE'
for f in tw_watchdog.sh tw_restart_guard.sh auto_shutdown.sh; do
  install -m 755 -o root -g root "/tmp/$f" "/usr/local/bin/$f"
done
rm -f /tmp/tw_watchdog.sh /tmp/tw_restart_guard.sh /tmp/auto_shutdown.sh

# 1) root crontab：watchdog 每 5 分鐘（idempotent）
if ! crontab -l 2>/dev/null | grep -Fq '/usr/local/bin/tw_watchdog.sh'; then
  { crontab -l 2>/dev/null; echo '*/5 * * * * /usr/local/bin/tw_watchdog.sh'; } | crontab -
  echo "   + root crontab: watchdog"
else
  echo "   = root crontab: watchdog（已存在）"
fi

# 2) /etc/cron.d：restart_guard
cat > /etc/cron.d/tw_restart_guard <<'CRON'
# 容器崩潰迴圈守門員（見 scripts/vm/tw_restart_guard.sh 與 cairn/deploy-pipeline.md）
# ⚠️ cron 用**系統時區**解讀時間欄位；這裡是「每 5 分鐘」，與時區無關。
*/5 * * * * root /usr/local/bin/tw_restart_guard.sh >> /var/log/tw_restart_guard.log 2>&1
CRON

# 3) /etc/cron.d：auto_shutdown（18:00 UTC = 02:00 台北）
cat > /etc/cron.d/auto_shutdown <<'CRON'
# 「忘記關機」安全網：正常情況 VM 已於台北 14:00 關機，此處僅防過夜未關。
# ⚠️ cron 用**系統時區**解讀時間欄位。本機時區 = UTC。
#    18:00 UTC = 2:00 台北。原設定 `0 2 * * *` 在 UTC 下實為台北 10:00，會在交易時段關機。
# 由 scripts/vm/install_vm_guards.sh 安裝（勿手改 VM 上的副本）。
0 18 * * * root /usr/local/bin/auto_shutdown.sh
CRON

chmod 644 /etc/cron.d/tw_restart_guard /etc/cron.d/auto_shutdown
echo "   ✓ /etc/cron.d/tw_restart_guard、auto_shutdown 已寫入"
REMOTE
[ $? -eq 0 ] || die "VM 端安裝失敗"

echo "🔍 驗證..."
remote 'echo "--- 已安裝 ---"
        ls -l /usr/local/bin/tw_watchdog.sh /usr/local/bin/tw_restart_guard.sh /usr/local/bin/auto_shutdown.sh | awk "{print \$1, \$3, \$NF}"
        echo "--- root crontab ---"; sudo crontab -l 2>/dev/null | grep -v "^#"
        echo "--- 容器與 watchdog 行為 ---"
        sudo /usr/local/bin/tw_watchdog.sh; echo "watchdog exit=$?（0 且無輸出＝容器健康、未發通知）"
        sudo docker ps --format "  {{.Names}} {{.Status}}"
        echo "--- restart_guard（只觀察）---"
        sudo DRY_RUN=1 GUARD_ALERT_ONLY=1 /usr/local/bin/tw_restart_guard.sh
        sudo tail -2 /var/log/tw_restart_guard.log'

echo ""
echo "✅ 完成。cron 下一輪（每 5 分鐘）起生效；告警只在真的需要時才會發。"
