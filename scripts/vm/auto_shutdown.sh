#!/bin/bash
# 「忘記關機」安全網：正常情況 VM 已於台北 14:00 關機，此處僅防過夜未關。
# ⚠️ cron 用**系統時區**解讀時間欄位。本機時區 = UTC。
#    18:00 UTC = 2:00 台北。
#    原設定 `0 2 * * *` 在 UTC 下實為台北 10:00，會在交易時段關機。
# 由 scripts/vm/install_vm_guards.sh 安裝（勿手改 VM 上的副本）。
logger -t auto_shutdown "02:00 檢查：VM 仍開著，自動關機（安全網）"
/sbin/shutdown -h now
