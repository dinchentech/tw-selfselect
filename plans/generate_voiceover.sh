#!/usr/bin/env bash
# =============================================================================
# generate_voiceover.sh · 從解說腳本重新生成配音（修改講稿後重跑用）
#
# 用法:
#   ./generate_voiceover.sh <script.md>              # 只重跑配音
#   ./generate_voiceover.sh <script.md> <ppt>        # 配音 + 更新講稿版/配音版 PPTX
#
# 說明:
#   - 適合「改了講稿內容 → 重新配音」的情境，不需要重新抽取 PPT
#   - 產出與 generate_narration.sh build 相同，但不必有原始 PPT
#
# 前置需求:
#   - node 18+, ffmpeg/ffprobe, python3 + python-pptx
#   - huashu-design skill + 豆包 TTS 金鑰（skill/.env 或環境變數）
# =============================================================================
set -euo pipefail

# ── 優先用專案 .venv 的 python（python-pptx／pypdfium2 裝在那裡）─────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$SCRIPT_DIR/../.venv/bin/python3" ]; then PYTHON="$SCRIPT_DIR/../.venv/bin/python3"; else PYTHON="python3"; fi

# ── 設定 ────────────────────────────────────────────────────────────────────
HUASHU_DIR="${HUASHU_DESIGN_DIR:-/home/frank/.agents/skills/huashu-design}"
PIPELINE="$HUASHU_DIR/scripts/narrate-pipeline.mjs"

die() { echo "❌ $*" >&2; exit 1; }
info() { echo "▶ $*"; }
ok()   { echo "✅ $*"; }

sanitize() {
  echo "$1" | sed 's/[^A-Za-z0-9._-]/_/g' | sed 's/\.md$//'
}

check_env() {
  command -v node    >/dev/null || die "找不到 node（需要 18+）"
  command -v ffprobe >/dev/null || die "找不到 ffprobe（apt install ffmpeg）"
  command -v python3 >/dev/null || die "找不到 python3"
  [ -f "$PIPELINE" ] || die "找不到 narrate-pipeline.mjs: $PIPELINE（設 HUASHU_DESIGN_DIR 指向 huashu-design skill 根目錄）"
  "$PYTHON" -c "import pptx" 2>/dev/null || die "缺少 python-pptx（pip install python-pptx）"
}

# ── 主流程 ─────────────────────────────────────────────────────────────────
[ $# -ge 1 ] || { echo "用法: $0 <script.md> [ppt]"; exit 1; }
SCRIPT_MD="$1"
PPT="${2:-}"
[ -f "$SCRIPT_MD" ] || die "講稿不存在: $SCRIPT_MD"
grep -q "^## slide-" "$SCRIPT_MD" || die "講稿格式不符（需 ## slide-N 分段）"
check_env

# 輸出位置：與講稿同目錄
SCRIPT_DIR="$(dirname "$SCRIPT_MD")"
BASE="$(basename "$SCRIPT_MD" .md)"
SAFE="$(sanitize "$(basename "$SCRIPT_MD")")"
PIPE_SCRIPT="$SCRIPT_DIR/${SAFE}-pipeline.md"
OUT_DIR="$SCRIPT_DIR/_narration_${SAFE}"

# 1. 講稿 → pipeline 專用稿（剝離講師提示/附錄/markdown 語法）
info "1/3 轉換 pipeline 講稿 → ${PIPE_SCRIPT##*/}"
"$PYTHON" - "$SCRIPT_MD" "$PIPE_SCRIPT" <<'PYEOF'
import re, sys
from pathlib import Path
src, out = Path(sys.argv[1]), Path(sys.argv[2])
text = src.read_text(encoding="utf-8").split("## 附錄")[0]
sections = re.split(r'^## slide-(\d+)\s+(.+)$', text, flags=re.M)
slides = {}
for i in range(1, len(sections), 3):
    slides[int(sections[i])] = sections[i+2].strip()
lines = ["---", f"title: {out.stem}", "gap: 0.4", "---", ""]
for num in range(1, max(slides) + 1):
    if num not in slides:
        print(f"  ⚠️ 跳過缺失頁 slide-{num}", file=sys.stderr)
        continue
    clean = []
    for para in slides[num].split('\n'):
        p = para.strip()
        if not p or p in ('---','***','___') or p.startswith('**講師提示**') or p.startswith('>'):
            continue
        clean.append(p.replace('**', ''))
    lines.append(f"## slide-{num}")
    lines.extend(clean)
    lines.append("")
out.write_text("\n".join(lines), encoding="utf-8")
PYEOF

# 2. 跑 narrate-pipeline（重新 TTS + 拼接 + timeline）
info "2/3 TTS 配音（依講稿長度約需 2-5 分鐘）"
node "$PIPELINE" --script "$PIPE_SCRIPT" --out-dir "$OUT_DIR" || die "narrate-pipeline 失敗"

TOTAL_MIN=""
TOTAL_MIN=$("$PYTHON" -c "
import json, sys
t = json.load(open(sys.argv[1]))
print(f'{t[\"totalDuration\"]/60:.1f} 分鐘')
" "$OUT_DIR/timeline.json")

# 3. 可選：更新 PPTX（提供 PPT 時）
if [ -n "$PPT" ]; then
  [ -f "$PPT" ] || die "簡報不存在: $PPT"
  PPT_BASE="${PPT%.pptx}"
  # 輸入若已是「-講稿版」，輸出檔名不要再疊一層
  OUT_BASE="${PPT_BASE%-講稿版}"
  NOTES_PPTX="$OUT_BASE-講稿版.pptx"
  VOICE_PPTX="$OUT_BASE-配音版.pptx"
  info "3/3 更新講稿版 + 配音版 PPTX"
  "$PYTHON" - "$PPT" "$SCRIPT_MD" "$OUT_DIR" "$NOTES_PPTX" "$VOICE_PPTX" <<'PYEOF'
import re, sys, hashlib, os
from pathlib import Path
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.oxml.ns import qn, nsdecls
from lxml import etree

ppt, script_md, out_dir, notes_pptx, voice_pptx = sys.argv[1:6]
AUDIO = Path(out_dir) / "audio"
AUDIO_44K = Path(out_dir) / "audio_44k"

# ── 重採樣為 44.1kHz 立體聲（PowerPoint 對嵌入 MP3 的相容要求）──
import subprocess
AUDIO_44K.mkdir(exist_ok=True)
for mp3 in sorted(AUDIO.glob("slide-*.mp3")):
    out = AUDIO_44K / mp3.name
    if not out.exists() or mp3.stat().st_mtime > out.stat().st_mtime:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-ar", "44100", "-ac", "2", "-b:a", "128k", str(out)], check=True)
AUDIO = AUDIO_44K

text = Path(script_md).read_text(encoding="utf-8").split("## 附錄")[0]
sections = re.split(r'^## slide-(\d+)\s+(.+)$', text, flags=re.M)
slides = {}
for i in range(1, len(sections), 3):
    slides[int(sections[i])] = (sections[i+1].strip(), sections[i+2].strip())

def strip_cue(t): return re.sub(r'\[\[cue:[^\]]+\]\]', '', t).strip()

def build_notes(title, body):
    m = re.search(r'（([^）]*(?:分鐘|秒)[^）]*)）', title)
    time_label = f"⏱ 建議時間：{m.group(1)}" if m else ""
    lines, tip = [], None
    for para in body.split('\n'):
        p = para.strip()
        if not p: continue
        if p.startswith('**講師提示**'):
            tip = p.replace('**講師提示**：', '').strip('* ')
            continue
        if p.startswith('>') or p in ('---','***','___'): continue
        lines.append(strip_cue(p))
    notes = ([time_label, ""] if time_label else []) + lines
    if tip: notes += ["", f"【講師提示】{tip}"]
    return "\n".join(notes)

prs = Presentation(ppt)
n = len(prs.slides)
missing = [i for i in range(1, n+1) if i not in slides]
if missing:
    raise SystemExit(f"講稿缺少頁: {missing}")
for idx, slide in enumerate(prs.slides, 1):
    title, body = slides[idx]
    slide.notes_slide.notes_text_frame.text = build_notes(title, body)
prs.save(notes_pptx)

prs2 = Presentation(notes_pptx)
from pptx.util import Emu as _Emu
_SW, _SH = prs2.slide_width, prs2.slide_height
_ICON = _Emu(360000)
_X, _Y = _SW - _ICON - _Emu(91440), _SH - _ICON - _Emu(91440)
for idx, slide in enumerate(prs2.slides, 1):
    mp3 = AUDIO / f"slide-{idx}.mp3"
    if not mp3.exists():
        raise SystemExit(f"缺音檔: {mp3}")
    # add_movie 官方模板：自動建立 media part + hlinkClick + p14:media + timing
    slide.shapes.add_movie(
        str(mp3), _X, _Y, _ICON, _ICON,
        poster_frame_image=None,
        mime_type='audio/mpeg',
    )
prs2.save(voice_pptx)

# ── 修正 [Content_Types].xml：補 mp3 Default 宣告（PowerPoint 相容要求）──
import zipfile as _zf, shutil as _sh, tempfile as _tf
_tmpd = _tf.mkdtemp()
with _zf.ZipFile(voice_pptx) as _z:
    _z.extractall(_tmpd)
_ct_path = _tmpd + "/[Content_Types].xml"
_ct = open(_ct_path, encoding="utf-8").read()
if 'Extension="mp3"' not in _ct:
    _ct = _ct.replace('  <Default Extension="mp3" ContentType="audio/mpeg"/>\n', '')
    _first_ov = _ct.find('<Override')
    _ct = _ct[:_first_ov] + '  <Default Extension="mp3" ContentType="audio/mpeg"/>\n' + _ct[_first_ov:]
    open(_ct_path, "w", encoding="utf-8").write(_ct)
    os.remove(voice_pptx)
    with _zf.ZipFile(voice_pptx, "w", _zf.ZIP_DEFLATED) as _z:
        for _root, _dirs, _files in os.walk(_tmpd):
            for _f in _files:
                _full = os.path.join(_root, _f)
                _z.write(_full, os.path.relpath(_full, _tmpd))
_sh.rmtree(_tmpd)

prs3 = Presentation(voice_pptx)
for i, slide in enumerate(prs3.slides, 1):
    assert "建議時間" in slide.notes_slide.notes_text_frame.text, f"第 {i} 頁缺備註"
    pics = slide.shapes._spTree.findall(qn('p:pic'))
    audio_pics = [p for p in pics if p.find(qn('p:nvPicPr')+'/'+qn('p:nvPr')+'/'+qn('a:videoFile')) is not None]
    assert len(audio_pics) == 1, f"第 {i} 頁 媒體形狀數 = {len(audio_pics)}"
    rid = audio_pics[0].find(qn('p:nvPicPr')+'/'+qn('p:nvPr')+'/'+qn('a:videoFile')).get(qn('r:link'))
    part = slide.part.related_part(rid)
    expect = (AUDIO / f"slide-{i}.mp3").read_bytes()
    assert hashlib.md5(part.blob).hexdigest() == hashlib.md5(expect).hexdigest(), f"第 {i} 頁音訊不一致"
print(f"  ✅ 驗證通過: {len(prs3.slides)} 頁備註+音訊全部正確")
PYEOF
  ok "全部完成！總配音時長 ${TOTAL_MIN}"
  echo "📄 ${NOTES_PPTX##*/}"
  echo "🎧 ${VOICE_PPTX##*/}"
  echo "🗣 $OUT_DIR/voiceover.mp3"
else
  ok "配音完成！總時長 ${TOTAL_MIN}"
  echo "🗣 $OUT_DIR/voiceover.mp3"
  echo "   （提供 PPT 路徑可一併更新講稿版/配音版 PPTX）"
fi
