#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# 部署到 GCP VM（源碼版）：本機建 image → SSH 直傳 → VM 載入重啟 → 驗指紋
#
#   ./deploy_source.sh                        # 預設 VM=tw-autotrader、ZONE=asia-east1-b、遠端 ~/tw-selfselect
#   ./deploy_source.sh my-vm asia-east1-b     # 指定 VM
#   SKIP_PREFLIGHT=1 ./deploy_source.sh       # 急修跳過測試（不建議）
#   KEEP_OLD_RUNNING=1 ./deploy_source.sh     # 不停舊的 tw_autotrader_bot（同帳號勿兩隻同時跑！）
#   VM_DIR=~/other-dir OLD_DIR=~/tw-autotrader ./deploy_source.sh
#   ENV_FILE=/path/to/.env ./deploy_source.sh # 第一次部署時改上傳你指定的 .env（預設自動產生）
#   INSTALL_GUARDS=1 ./deploy_source.sh       # 順帶同步 VM 上的守門員（scripts/vm/install_vm_guards.sh）
#
# 與 tw-autotrader/deploy_source.sh 的差異
#   · 這支不碰 live_trader_multi.py／plans 備份（本專案沒有那條腿）
#   · 不走 Cloud Storage（本專案沒有 GCS bucket）：一律 **SSH 直傳**
#     `docker save | gzip | ssh 'gunzip | docker load'`（e2-micro 只有 1GB RAM，
#     遠端只跑原生 gunzip/docker load，不在 VM 上跑 gcloud 串流，避免 OOM）
#   · 遠端目錄預設 `~/tw-selfselect`；舊的 `~/tw-autotrader` **原地保留** ⇒ 回滾一行指令
#   · whl 已進版控（玉山下載頁公開、免登入）⇒ 建 image 只需 git；不進版控的
#     p12 與舊 image 內的 `config.simulation.ini` 只在缺檔時自動補
#   · 第一次部署（遠端 .env 不存在）會自動：
#       ① 用 `scripts/make_selfselect_env.py` 產生 `~/tw-selfselect/.env`
#          （只帶白名單鍵＋secrets；PC_ 清空＝重置模式；MODELC_EXEC_MODE→SELFSELECT_EXEC_MODE）
#       ② 把舊 `cache/` 複製到新目錄（cache schema 兩邊都是 v2）
#   · 部署成功會比對 build fingerprint（core/version.py）；不符就 exit 1
#   · **刻意不做 `docker system prune`**：舊 image 留著，回滾才不必重新 build
# ══════════════════════════════════════════════════════════════════════════
set -uo pipefail

# 一律以 repo 根目錄為工作目錄（腳本用相對路徑找 Dockerfile／.env.example.txt／scripts/）
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1

VM_NAME="${1:-tw-autotrader}"
ZONE="${2:-asia-east1-b}"
VM_DIR="${VM_DIR:-~/tw-selfselect}"
OLD_DIR="${OLD_DIR:-~/tw-autotrader}"
OLD_CONTAINER="${OLD_CONTAINER:-tw_autotrader_bot}"
IMAGE="${IMAGE:-tw-selfselect}"
CONTAINER="${CONTAINER:-tw_selfselect_bot}"

SSH_OPTS=(--zone="${ZONE}" --quiet --ssh-flag=-o --ssh-flag=ServerAliveInterval=60)
SCP_OPTS=(--zone="${ZONE}" --quiet)

die() { echo ""; echo "❌ $*"; exit 1; }
remote() { gcloud compute ssh "${VM_NAME}" "${SSH_OPTS[@]}" --command="$1"; }
scp_to() { gcloud compute scp "$1" "${VM_NAME}:$2" "${SCP_OPTS[@]}"; }
scp_from() { gcloud compute scp "${VM_NAME}:$1" "$2" "${SCP_OPTS[@]}"; }

PY="python3"
[ -x .venv/bin/python ] && PY=".venv/bin/python"

echo "════════════════════════════════════════════════════════════════════"
echo " 部署 tw-selfselect → ${VM_NAME}（${ZONE}）｜遠端目錄 ${VM_DIR}"
echo "════════════════════════════════════════════════════════════════════"

# ── 1. 前置檢查 ─────────────────────────────────────────────────────
echo "🔑 檢查 GCP 認證..."
gcloud auth print-identity-token &>/dev/null || die "GCP 認證過期：先跑 \`gcloud auth login\`"
echo "   ✅ 認證有效"

echo "🖥  檢查 VM 狀態..."
VM_STATUS=$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --format="get(status)" 2>&1)
[ "${VM_STATUS}" = "RUNNING" ] || die "VM 狀態=${VM_STATUS:-未知}。非交易時段會自動關機，請先開機：
   gcloud compute instances start ${VM_NAME} --zone=${ZONE}"
echo "   ✅ VM 運行中"

# 工作區未提交變更只是警告（image 打包的是工作區，不是最後一個 commit）
DIRTY=$(git status --porcelain 2>/dev/null \
        | grep -vE '^\s*(\?\?|..)\s+(cache|logs|backups|results|TMP|esun_sdk)/' \
        | grep -vE '(\.env|capital\.txt|\*\.Zone\.Identifier)' | grep -c . || true)
[ "${DIRTY:-0}" -gt 0 ] && echo "   ⚠️  工作區有 ${DIRTY} 個會被打包進 image 的未提交變更（建議先 commit）"

# ── 2. 部署前測試 ───────────────────────────────────────────────────
if [ "${SKIP_PREFLIGHT:-0}" = "1" ]; then
  echo "⚠️  SKIP_PREFLIGHT=1 ⇒ 跳過部署前測試"
else
  bash scripts/preflight_deploy.sh || die "部署前測試沒過（修好再部署；急修才用 SKIP_PREFLIGHT=1）"
fi

# ── 3. 補齊本機 esun_sdk（whl 由 git 帶入；只補「不進版控」的兩樣）──────
# 玉山 SDK 的 whl 已進版控（官方下載頁公開、免登入）⇒ clone/pull 就有。
# 不進版控的是：
#   ① p12 憑證（VM 舊目錄有）
#   ② config.simulation.ini（券商帳號／API key；只在舊 image 的 /app/esun_sdk/ 裡）
mkdir -p esun_sdk
ls esun_sdk/*.whl >/dev/null 2>&1 \
  || die "esun_sdk/ 沒有 whl（應由 git 帶入）⇒ 先 git pull，或手動放 whl 到 esun_sdk/ 後重試"

if ! ls esun_sdk/*.p12 >/dev/null 2>&1; then
  echo "📦 本機沒有 p12 憑證 ⇒ 從 ${VM_NAME}:${OLD_DIR}/esun_sdk 取..."
  P12_REMOTE=$(remote "ls ${OLD_DIR}/esun_sdk/*.p12 2>/dev/null | head -1" | tr -d '\r' | tail -1)
  [ -n "${P12_REMOTE}" ] \
    || die "VM 的 ${OLD_DIR}/esun_sdk/ 沒有 p12：請手動放到 esun_sdk/（憑證向玉山取得）"
  scp_from "${P12_REMOTE}" "esun_sdk/$(basename "${P12_REMOTE}")" \
    || die "下載 p12 失敗"
fi

if [ ! -f esun_sdk/config.simulation.ini ]; then
  echo "📦 本機缺 esun_sdk/config.simulation.ini ⇒ 從舊 image 取出（登入必需）..."
  remote "sudo docker cp ${OLD_CONTAINER}:/app/esun_sdk/config.simulation.ini /tmp/config.simulation.ini" \
    || die "取不到 config.simulation.ini：請手動放到 esun_sdk/config.simulation.ini（內容同舊 image）"
  scp_from "/tmp/config.simulation.ini" "esun_sdk/config.simulation.ini" \
    || die "下載 config.simulation.ini 失敗"
  remote "sudo rm -f /tmp/config.simulation.ini"
fi
echo "   ✅ esun_sdk：$(ls esun_sdk/*.whl | wc -l) whl（git）／$(ls esun_sdk/*.p12 2>/dev/null | wc -l) p12／ini=$([ -f esun_sdk/config.simulation.ini ] && echo yes || echo no)"

# ── 4. 建 image ─────────────────────────────────────────────────────
echo "🐳 建置 image ${IMAGE}..."
docker build -t "${IMAGE}" . || die "docker build 失敗"
BUILD_FP=$("${PY}" -c "import sys; sys.path.insert(0,'.'); from core.version import build_info; print(build_info()[1])" 2>/dev/null || echo unknown)
echo "   🔎 預期容器指紋：${BUILD_FP}（源碼版不加密 ⇒ banner 應顯示同一組）"

# ── 5. 遠端目錄／compose／.env／cache ───────────────────────────────
echo "📁 準備遠端目錄 ${VM_DIR}..."
remote "mkdir -p ${VM_DIR}/logs ${VM_DIR}/backups ${VM_DIR}/cache" >/dev/null 2>&1 \
  || die "建立遠端目錄失敗"

echo "📄 同步 docker-compose.yml..."
scp_to docker-compose.yml "${VM_DIR}/docker-compose.yml" || die "上傳 docker-compose.yml 失敗"

ENV_EXISTS=$(remote "test -f ${VM_DIR}/.env && echo yes || echo no" | tr -d '\r' | tail -1)
if [ "${ENV_EXISTS}" = "yes" ]; then
  echo "🔧 ${VM_DIR}/.env 已存在 ⇒ 保留（不覆蓋）"
elif [ -n "${ENV_FILE:-}" ] && [ -f "${ENV_FILE}" ]; then
  echo "🔧 上傳指定的 ENV_FILE=${ENV_FILE}..."
  scp_to "${ENV_FILE}" "${VM_DIR}/.env" || die "上傳 .env 失敗"
else
  echo "🔧 第一次部署：從 ${OLD_DIR}/.env 產生 ${VM_DIR}/.env（重置模式：PC_ 清空）..."
  scp_to .env.example.txt "/tmp/tw-selfselect.env.example.txt" || die "上傳 .env.example.txt 失敗"
  scp_to scripts/make_selfselect_env.py "/tmp/make_selfselect_env.py" || die "上傳 env 產生器失敗"
  remote "python3 /tmp/make_selfselect_env.py --example /tmp/tw-selfselect.env.example.txt --source ${OLD_DIR}/.env --dest ${VM_DIR}/.env --write" \
    || die "產生 .env 失敗（檢查 ${OLD_DIR}/.env 是否存在）"
  # 把範本佔位值 SYNC_VM_NAME=my-vm 換成這台 VM 的名字（--sync-* 功能要用）
  remote "sed -i 's/^SYNC_VM_NAME=.*/SYNC_VM_NAME=${VM_NAME}/' ${VM_DIR}/.env" || true
  remote "rm -f /tmp/tw-selfselect.env.example.txt /tmp/make_selfselect_env.py"
fi
remote "test -s ${VM_DIR}/.env" || die "遠端 .env 不存在或為空（compose 起不來）"
remote "grep -q '^KEYRING_CRYPTFILE_PASSWORD=' ${VM_DIR}/.env" \
  || echo "   ⚠️  .env 沒有 KEYRING_CRYPTFILE_PASSWORD ⇒ 玉山登入會失敗（tw-selfselect 不提供預設值）"

CACHE_EMPTY=$(remote "[ -n \"\$(ls -A ${VM_DIR}/cache 2>/dev/null)\" ] && echo no || echo yes" | tr -d '\r' | tail -1)
if [ "${CACHE_EMPTY}" = "yes" ]; then
  echo "🗃  新目錄 cache 是空的 ⇒ 從 ${OLD_DIR}/cache 複製（schema 兩邊都是 v2）..."
  remote "test -d ${OLD_DIR}/cache && cp -a ${OLD_DIR}/cache/. ${VM_DIR}/cache/ || true"
  remote "du -sh ${VM_DIR}/cache 2>/dev/null" | sed 's/^/   /'
else
  echo "🗃  ${VM_DIR}/cache 已有資料 ⇒ 不覆蓋"
fi

# ── 6. 先傳 image → VM 載入（失敗時舊 bot 還在跑，交易不受影響）──────
echo "🚚 SSH 直傳 image（docker save | gzip | ssh 'gunzip | docker load'）..."
if ! ( docker save "${IMAGE}" | gzip -1 | gcloud compute ssh "${VM_NAME}" "${SSH_OPTS[@]}" \
        --command="gunzip | sudo docker load" ); then
  stty sane 2>/dev/null
  die "image 傳輸／載入失敗（VM 磁碟或記憶體）。舊 bot 不受影響；現況：
   gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='sudo docker ps -a | head'"
fi
stty sane 2>/dev/null
echo "   ✅ image 已載入"

# ── 7. 停舊 bot（避免兩隻同時對同一個券商帳號下單）────────────────────
if [ "${KEEP_OLD_RUNNING:-0}" = "1" ]; then
  echo "⚠️  KEEP_OLD_RUNNING=1 ⇒ 不停舊容器（同一個券商帳號勿兩隻同時跑）"
else
  echo "🛑 停舊 bot（${OLD_DIR}）..."
  if remote "test -f ${OLD_DIR}/docker-compose.yml" >/dev/null 2>&1; then
    remote "cd ${OLD_DIR} && sudo docker compose down" >/dev/null 2>&1 \
      && echo "   ✅ 舊容器已停（image 與目錄保留 ⇒ 可回滾）" \
      || echo "   ⚠️  停舊容器失敗（若原本沒在跑可忽略）"
  else
    echo "   ℹ️  ${OLD_DIR} 沒有 compose 檔 ⇒ 跳過"
  fi
fi

# ── 8. 重啟容器 ─────────────────────────────────────────────────────
echo "🚀 啟動 ${CONTAINER}..."
remote "cd ${VM_DIR} && sudo docker compose up -d --force-recreate" || die "docker compose up 失敗"
stty sane 2>/dev/null

# ── 9. 驗證 ─────────────────────────────────────────────────────────
echo "🔍 驗證容器..."
CT_STATUS=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  CT_STATUS=$(remote "sudo docker inspect ${CONTAINER} --format '{{.State.Status}}'" 2>/dev/null | tr -d '\r' | tail -1)
  [ "${CT_STATUS}" = "running" ] && break
  sleep 1
done
ACTUAL_FP=$(remote "sudo docker exec ${CONTAINER} python -c \"import core.version as v; print(v.APP_VERSION, v.build_info()[1])\"" 2>/dev/null | tr -d '\r' | tail -1)
stty sane 2>/dev/null
echo "   容器狀態: ${CT_STATUS:-unknown}｜版本/指紋: ${ACTUAL_FP:-unknown}"
if [ "${CT_STATUS}" = "running" ] && [ -n "${ACTUAL_FP}" ] && [ "${ACTUAL_FP##* }" = "${BUILD_FP}" ]; then
  echo "   ✅ 指紋相符"
else
  remote "sudo docker logs ${CONTAINER} --tail 30" 2>/dev/null | sed 's/^/   /'
  die "指紋不符或容器沒起來（預期 ${BUILD_FP}）——容器裡跑的不是這次建置的版本"
fi

echo ""
echo "📋 最近日誌（前 20 行）："
remote "sudo docker logs ${CONTAINER} --tail 20" 2>/dev/null | sed 's/^/   /'
stty sane 2>/dev/null

echo ""
echo "✅ 部署完成"

if [ "${INSTALL_GUARDS:-0}" = "1" ]; then
  echo ""
  echo "🛡  同步 VM 守門員（watchdog／restart_guard／auto_shutdown）..."
  if bash scripts/vm/install_vm_guards.sh "${VM_NAME}" "${ZONE}"; then
    echo "   ✅ 守門員已同步"
  else
    echo "   ⚠️ 守門員同步失敗（不影響本次部署；可稍後單獨重跑 scripts/vm/install_vm_guards.sh）"
  fi
fi
echo ""
echo "下一步（VM 上執行）："
echo "  1) 對帳模擬券商帳戶（重置後帳本與券商持倉會不一致，這是預期的）："
echo "     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='sudo docker exec ${CONTAINER} python scripts/reconcile_broker_books.py'"
echo "  2) 立即產生名單（或等 D1 13:36 自動選股；SELFSELECT_AUTO=1）："
echo "     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='sudo docker exec ${CONTAINER} python scripts/monthly_selfselect_run.py --risk normal --top-n 5 --apply'"
echo "  3) 回滾到舊 tw-autotrader（舊 image 保留、目錄未動）："
echo "     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='cd ${OLD_DIR} && sudo docker compose up -d'"
