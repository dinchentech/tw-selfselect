#!/usr/bin/env bash
# =============================================================================
# why_to_mp4.sh · why_design.pptx（直式 9:16）→ 短視頻 MP4
#
# 特色：每頁**緩慢推軌（Ken Burns）＋交叉淡入轉場**。PPT 內建動畫在
#       LibreOffice 轉檔時會被拍掉，所以「動」是在影片層用 ffmpeg 做出來的。
#
# 用法:
#   bash plans/ppt/why_to_mp4.sh                       # 預設 plans/ppt/why_design.pptx
#   bash plans/ppt/why_to_mp4.sh <deck.pptx> [out.mp4]
#
# 可調（環境變數）:
#   SLIDE_SEC=6   每頁秒數（有配音時自動改用 timeline.json 的時長）
#   FADE=0.7      轉場秒數（0 = 硬切）
#   ZOOM=1.08     推軌倍率（1.0 = 不動）
#   NARR=<dir>    配音目錄（_narration_*/ 內含 timeline.json + audio/slide-N.mp3）
#   W=1080 H=1920 FPS=30   成品解析度（直式 1080p，預設）
#   SS=1.5        內部超取樣倍率（推軌用；1 = 不超取樣最快，2 = 最平滑但最慢）
#
# 前置需求: soffice（PPTX→PDF）、pypdfium2（PDF→PNG，裝在專案 .venv）、ffmpeg
# 產出: 預設 <deck>.mp4（1080×1920、H.264、yuv420p、faststart）
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ -x "$ROOT/.venv/bin/python3" ]; then PYTHON="$ROOT/.venv/bin/python3"; else PYTHON="python3"; fi

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "▶ $*"; }
ok() { echo "✅ $*"; }

DECK="${1:-$ROOT/plans/ppt/why_design.pptx}"
[ -f "$DECK" ] || die "找不到簡報: $DECK"
OUT="${2:-${DECK%.pptx}.mp4}"

command -v soffice >/dev/null || die "找不到 soffice/libreoffice"
command -v ffmpeg >/dev/null || die "找不到 ffmpeg"
"$PYTHON" -c "import pypdfium2" 2>/dev/null || die "缺少 pypdfium2（pip install pypdfium2）"

SLIDE_SEC="${SLIDE_SEC:-6}"
FADE="${FADE:-0.7}"
ZOOM="${ZOOM:-1.08}"
W="${W:-1080}"
H="${H:-1920}"
FPS="${FPS:-30}"
SS="${SS:-1.5}"
NARR="${NARR:-}"

# LibreOffice 在無 root／沙箱環境會寫 $HOME/.config ⇒ 給它一個可寫的 profile
export HOME="${HOME_OVERRIDE:-$ROOT/TMP/lohome}"
mkdir -p "$HOME"
LO_ARGS=(-env:UserInstallation="file://$HOME/lo-profile" --headless --norestore)

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

info "1/3 PPTX → PDF（LibreOffice）..."
soffice "${LO_ARGS[@]}" --convert-to pdf --outdir "$TMP" "$DECK" >/dev/null 2>&1
PDF="$TMP/$(basename "${DECK%.pptx}").pdf"
[ -f "$PDF" ] || die "PDF 轉換失敗"

info "2/3 PDF → 逐頁 PNG + 影片組裝（成品 ${W}×${H}、Ken Burns ${ZOOM}×／轉場 ${FADE}s／超取樣 ${SS}×）..."
"$PYTHON" - "$PDF" "$TMP" "$OUT" "$SLIDE_SEC" "$FADE" "$ZOOM" "$W" "$H" "$FPS" "$NARR" "$SS" <<'PYEOF'
import json, pathlib, shutil, subprocess, sys

pdf_path, tmp, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
slide_sec, fade, zoom, W, H, FPS = (float(sys.argv[4]), float(sys.argv[5]), float(sys.argv[6]),
                                    int(sys.argv[7]), int(sys.argv[8]), int(sys.argv[9]))
narr_dir = pathlib.Path(sys.argv[10]) if sys.argv[10] else None
ss = max(1.0, float(sys.argv[11]))                 # 內部超取樣倍率（只影響推軌平滑度）

import pypdfium2 as pdfium

pdf = pdfium.PdfDocument(str(pdf_path))
# 逐頁渲染 → **先用 PIL 放大到 2×（每頁只做一次）**，這樣 ffmpeg 不用逐格重新縮放
from PIL import Image

pngs = []
for i in range(len(pdf)):
    page = pdf[i]
    img = page.render(scale=W / page.get_width() * ss).to_pil().convert("RGB")
    img = img.resize((round(W * ss), round(H * ss)), Image.LANCZOS)   # 留邊給 zoompan，避免推軌抖動
    p = tmp / f"slide-{i + 1:02d}.png"
    img.save(p, compress_level=1)
    pngs.append(p)
print(f"  {len(pngs)} 頁 → PNG（內部 {ss}×、成品 {W}×{H}）")

# ── 每頁時長：有配音就用 timeline.json，否則固定 SLIDE_SEC
durations = [slide_sec] * len(pngs)
audios = [None] * len(pngs)
if narr_dir:
    tl = json.load(open(narr_dir / "timeline.json"))
    for sc in tl.get("scenes", []):
        try:
            idx = int(sc["id"].split("-")[1]) - 1
            durations[idx] = float(sc["duration"])
        except Exception:
            pass
    audio_dir = narr_dir / "audio" if (narr_dir / "audio").is_dir() else narr_dir / "audio_44k"
    for i in range(len(pngs)):
        a = audio_dir / f"slide-{i + 1}.mp3"
        if a.is_file():
            audios[i] = a
    if fade > 0:                       # 有配音 ⇒ 硬切，字幕/旁白才對得上
        print("  ⚠️ 有配音 ⇒ 轉場改為硬切（FADE=0），確保旁白與畫面同步")
        fade = 0.0

fade = min(fade, min(durations) / 2.5) if fade else 0.0
frames = [max(1, round(d * FPS)) for d in durations]

# ── 每頁：放大 2× → zoompan（同頁內緩推，方向逐頁交替）→ 1080×1920
inputs, chains = [], []
pan = [(-0.30, -0.20), (0.30, -0.20), (-0.30, 0.20), (0.30, 0.20), (0.0, -0.28), (-0.28, 0.0)]
for i, (png, n) in enumerate(zip(pngs, frames)):
    inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{n / FPS:.3f}", "-i", str(png)]
    px, py = pan[i % len(pan)]
    z = f"min(1+({zoom}-1)*on/{max(1, n - 1)},{zoom})"
    x = f"iw/2-(iw/zoom/2)+({px})*(iw-iw/zoom)/2"
    y = f"ih/2-(ih/zoom/2)+({py})*(ih-ih/zoom)/2"
    chains.append(
        f"[{i}:v]zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS},"
        f"setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{i}]"
    )

# ── 轉場：xfade 串接（offset = 前面累計長度 − 已用掉的淡入量）
if fade > 0 and len(pngs) > 1:
    cur, offset = "v0", 0.0
    for i in range(1, len(pngs)):
        offset += durations[i - 1] - fade
        label = f"x{i}"
        chains.append(f"[{cur}][v{i}]xfade=transition=fade:duration={fade}:offset={offset:.3f}[{label}]")
        cur = label
    vout = cur
else:
    chains.append("".join(f"[v{i}]" for i in range(len(pngs))) +
                  f"concat=n={len(pngs)}:v=1:a=0[vout]")
    vout = "vout"

# ── 音訊：有配音才接（每段用 adelay 對齊它在時間軸上的起點）
total = sum(durations) - fade * (len(pngs) - 1)
maps = ["-map", f"[{vout}]"]
if any(audios):
    starts, acc = [], 0.0
    for i, d in enumerate(durations):
        starts.append(acc)
        acc += d - (fade if fade else 0.0)
    alabels = []
    for i, a in enumerate(audios):
        if a is None:
            continue
        inputs += ["-i", str(a)]
        ai = len(pngs) + len(alabels)
        ms = int(starts[i] * 1000)
        chains.append(f"[{ai}:a]adelay={ms}|{ms},apad[a{i}]")
        alabels.append(f"[a{i}]")
    chains.append("".join(alabels) + f"amix=inputs={len(alabels)}:normalize=0,atrim=0:{total:.3f}[aout]")
    maps += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]

cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs,
       "-filter_complex", ";".join(chains), *maps,
       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
       "-pix_fmt", "yuv420p", "-r", str(FPS), "-ar", "44100", "-t", f"{total:.3f}",
       "-movflags", "+faststart", str(out)]
print(f"  總長 {total:.1f}s（{len(pngs)} 頁、轉場 {fade}s、推軌 {zoom}×）")
subprocess.run(cmd, check=True)
PYEOF

[ -f "$OUT" ] || die "MP4 產生失敗"
ok "產出 $OUT（$(du -h "$OUT" | cut -f1)）"
info "想加旁白：把配音目錄指定進來，例如 NARR=plans/ppt/_narration_why_design bash plans/ppt/why_to_mp4.sh"
