#!/usr/bin/env bash
# =============================================================================
# ppt_to_mp4.sh · PPT + 配音檔 → MP4（簡報畫面 + 旁白）
#
# 用法:
#   ./ppt_to_mp4.sh <deck.pptx>                              # 自動找配音目錄
#   ./ppt_to_mp4.sh <deck.pptx> <narration_dir> [out.mp4]    # 指定配音目錄
#
# 配音目錄 = generate_voiceover.sh 產出的 _narration_*/（內含 timeline.json +
# audio/slide-N.mp3）。每頁停留時間取自 timeline.json 的場景時長。
#
# 前置需求:
#   - libreoffice/soffice（PPTX → PDF）
#   - python3 + pypdfium2（PDF → PNG；pip install pypdfium2）
#   - ffmpeg/ffprobe
#
# 產出: <deck>.mp4（H.264 + AAC，與配音總時長一致）
# =============================================================================
set -euo pipefail

# ── 優先用專案 .venv 的 python（python-pptx／pypdfium2 裝在那裡）─────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$SCRIPT_DIR/../.venv/bin/python3" ]; then PYTHON="$SCRIPT_DIR/../.venv/bin/python3"; else PYTHON="python3"; fi

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "▶ $*"; }
ok()   { echo "✅ $*"; }

[ $# -ge 1 ] || { echo "用法: $0 <deck.pptx> [narration_dir] [out.mp4]"; exit 1; }
PPT="$1"
NARR_DIR="${2:-}"
OUT="${3:-}"
[ -f "$PPT" ] || die "簡報不存在: $PPT"
command -v soffice >/dev/null || die "找不到 soffice/libreoffice"
command -v ffmpeg >/dev/null || die "找不到 ffmpeg"
"$PYTHON" -c "import pypdfium2" 2>/dev/null || die "缺少 pypdfium2（pip install pypdfium2）"

PPT_DIR="$(dirname "$(realpath "$PPT")")"
PPT_BASE="$(basename "$PPT" .pptx)"
SAFE="$(echo "$PPT_BASE" | sed 's/[^A-Za-z0-9._-]/_/g')"

# ── 自動找配音目錄（優先「解說腳本」衍生名，再取 timeline.json 最新者）──
if [ -z "$NARR_DIR" ]; then
  SCRIPT_SAFE="$(echo "${PPT_BASE}-解說腳本" | sed 's/[^A-Za-z0-9._-]/_/g')"
  CANDIDATES=("$PPT_DIR/_narration_${SCRIPT_SAFE}" "$PPT_DIR/_narration_${SAFE}-____" "$PPT_DIR/_narration_${SAFE}")
  BEST=""
  for c in "${CANDIDATES[@]}"; do
    [ -f "$c/timeline.json" ] || continue
    if [ -z "$BEST" ] || [ "$c/timeline.json" -nt "$BEST/timeline.json" ]; then
      BEST="$c"
    fi
  done
  if [ -z "$BEST" ]; then
    FOUND=($(ls -d "$PPT_DIR"/_narration_* 2>/dev/null || true))
    if [ ${#FOUND[@]} -eq 1 ]; then BEST="${FOUND[0]}"; fi
  fi
  NARR_DIR="$BEST"
fi
[ -n "$NARR_DIR" ] && [ -f "$NARR_DIR/timeline.json" ] || {
  echo "❌ 找不到配音目錄（需要 timeline.json）。可用目錄:"; ls -d "$PPT_DIR"/_narration_* 2>/dev/null || true; exit 1; }
info "使用配音目錄: ${NARR_DIR##*/}"
AUDIO_DIR="$NARR_DIR/audio"
[ -d "$AUDIO_DIR" ] || AUDIO_DIR="$NARR_DIR/audio_44k"
[ -d "$AUDIO_DIR" ] || die "配音目錄缺少 audio/ 或 audio_44k/: $NARR_DIR"
[ -n "$OUT" ] || OUT="$PPT_DIR/${PPT_BASE}.mp4"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
info "1/4 PPTX → PDF（LibreOffice）..."
soffice --headless --convert-to pdf --outdir "$TMP" "$PPT" >/dev/null 2>&1
PDF="$TMP/$(basename "$PPT" .pptx).pdf"
[ -f "$PDF" ] || die "PDF 轉換失敗"

info "2/4 PDF → 逐頁 PNG（pypdfium2）..."
"$PYTHON" - "$PDF" "$TMP" <<'PYEOF'
import sys, pathlib
import pypdfium2 as pdfium
pdf_path, out_dir = sys.argv[1], pathlib.Path(sys.argv[2])
pdf = pdfium.PdfDocument(pdf_path)
n = len(pdf)
for i in range(n):
    page = pdf[i]
    bitmap = page.render(scale=2.0)  # 2x ≈ 150 DPI，足夠 1080p
    bitmap.to_pil().save(out_dir / f"slide-{i+1:03d}.png")
print(f"  渲染 {n} 頁")
PYEOF

info "3/4 讀取 timeline 時長 + 逐頁合成..."
"$PYTHON" - "$NARR_DIR/timeline.json" "$TMP" "$AUDIO_DIR" <<'PYEOF'
import json, pathlib, subprocess, sys
tl = json.load(open(sys.argv[1]))
tmp, audio_dir = pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
durations = {}
for s in tl["scenes"]:
    try:
        durations[int(s["id"].split("-")[1])] = float(s["duration"])
    except Exception:
        pass
seg_list = []
max_slide = max(durations) if durations else 1
for i in range(1, max_slide + 1):
    dur = durations.get(i)
    if dur is None:
        dur = 8.0
        print(f"  ⚠️ slide-{i} 無時長，預設 {dur}s")
    img = tmp / f"slide-{i:03d}.png"
    mp3 = audio_dir / f"slide-{i}.mp3"
    seg = tmp / f"seg-{i:03d}.mp4"
    if not img.exists() or not mp3.exists():
        print(f"  ⚠️ 缺 {img.name} 或 {mp3.name}，跳過")
        continue
    # -af apad 把音訊補到 -t 的長度，避免 -shortest 提前截斷造成總長少 1~2 秒
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-loop", "1", "-framerate", "30", "-i", str(img),
                    "-i", str(mp3), "-af", "apad", "-t", f"{dur:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
                    "-c:a", "aac", "-b:a", "128k", "-pix_fmt", "yuv420p",
                    str(seg)], check=True)
    seg_list.append(str(seg))
list_file = tmp / "concat.txt"
list_file.write_text("\n".join(f"file '{s}'" for s in seg_list) + "\n")
print(f"  合成 {len(seg_list)} 段")
PYEOF

info "4/4 concat → 最終 MP4..."
ffmpeg -y -loglevel error -f concat -safe 0 -i "$TMP/concat.txt" -c copy "$OUT"

TOTAL_JSON=$("$PYTHON" -c "
import json,sys
t=json.load(open(sys.argv[1])); print(f'{t[\"totalDuration\"]:.1f}')" "$NARR_DIR/timeline.json")
OUT_DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$OUT")
ok "完成！${OUT##*/}（配音 ${TOTAL_JSON}s / 實際 ${OUT_DUR%.*}s）"
echo "📹 $OUT"
