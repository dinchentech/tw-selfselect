#!/usr/bin/env bash
# =============================================================================
# generate_narration.sh · TW-SELFSELECT 課程簡報 → 解說配音流水線
#
# 用法:
#   ./generate_narration.sh extract <ppt>                  # 1. 抽取逐頁文字（給 AI 寫講稿用）
#   ./generate_narration.sh build   <ppt> <script.md>      # 2. 講稿 → 配音 + 講稿版 + 配音版
#
# 前置需求:
#   - node 18+, ffmpeg/ffprobe, python3 + python-pptx
#   - huashu-design skill（內含 narrate-pipeline.mjs / tts-doubao.mjs）
#   - 豆包 TTS 金鑰: skill/.env 或環境變數 DOUBAO_TTS_API_KEY / DOUBAO_TTS_VOICE_ID
#
# 產出（與 PPT 同目錄）:
#   <名稱>-解說腳本.md      （由 AI 產生，本腳本不覆寫）
#   <名稱>-講稿版.pptx      （講稿寫入每頁備註）
#   <名稱>-配音版.pptx      （講稿備註 + 每頁嵌入音訊）
#   _narration_<名稱>/      （voiceover.mp3 + timeline.json + audio/slide-N.mp3）
# =============================================================================
set -euo pipefail

# ── 優先用專案 .venv 的 python（python-pptx／pypdfium2 裝在那裡）─────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$SCRIPT_DIR/../.venv/bin/python3" ]; then PYTHON="$SCRIPT_DIR/../.venv/bin/python3"; else PYTHON="python3"; fi

# ── 設定 ────────────────────────────────────────────────────────────────────
HUASHU_DIR="${HUASHU_DESIGN_DIR:-/home/frank/.agents/skills/huashu-design}"
PIPELINE="$HUASHU_DIR/scripts/narrate-pipeline.mjs"

# ── 小工具 ──────────────────────────────────────────────────────────────────
die() { echo "❌ $*" >&2; exit 1; }
info() { echo "▶ $*"; }
ok()   { echo "✅ $*"; }

sanitize() {  # 中文檔名 → 安全目錄名（保留英文數字連字號，其餘轉底線）
  echo "$1" | sed 's/[^A-Za-z0-9._-]/_/g' | sed 's/\.pptx$//'
}

check_env() {
  command -v node    >/dev/null || die "找不到 node（需要 18+）"
  command -v ffprobe >/dev/null || die "找不到 ffprobe（apt install ffmpeg）"
  command -v python3 >/dev/null || die "找不到 python3"
  [ -f "$PIPELINE" ] || die "找不到 narrate-pipeline.mjs: $PIPELINE（設 HUASHU_DESIGN_DIR 指向 huashu-design skill 根目錄）"
  "$PYTHON" -c "import pptx" 2>/dev/null || die "缺少 python-pptx（pip install python-pptx）"
}

# ── 子命令: extract ─────────────────────────────────────────────────────────
cmd_extract() {
  local ppt="$1"
  [ -f "$ppt" ] || die "檔案不存在: $ppt"
  local out="${ppt%.pptx}-內容.txt"
  "$PYTHON" - "$ppt" "$out" <<'PYEOF'
import sys
from pptx import Presentation

ppt, out = sys.argv[1], sys.argv[2]
prs = Presentation(ppt)

def shape_text(shape):
    texts = []
    if shape.has_text_frame:
        for para in shape.text_frame.paragraphs:
            t = "".join(run.text for run in para.runs).strip()
            if t:
                texts.append(t)
    if shape.has_table:
        for row in shape.table.rows:
            texts.append(" | ".join(c.text.strip() for c in row.cells))
    return texts

lines = []
for i, slide in enumerate(prs.slides, 1):
    lines.append(f"===== SLIDE {i} =====")
    for shape in slide.shapes:
        for t in shape_text(shape):
            lines.append(f"  {t}")
    if slide.has_notes_slide:
        n = slide.notes_slide.notes_text_frame.text.strip()
        if n:
            lines.append(f"  [NOTES] {n}")
    lines.append("")

open(out, "w", encoding="utf-8").write("\n".join(lines))
print(f"✅ 已抽取 {len(prs.slides)} 頁 → {out}")
PYEOF
}

# ── 子命令: build ───────────────────────────────────────────────────────────
cmd_build() {
  local ppt="$1" script_md="$2"
  [ -f "$ppt" ]      || die "簡報不存在: $ppt"
  [ -f "$script_md" ] || die "講稿不存在: $script_md"
  grep -q "^## slide-" "$script_md" || die "講稿格式不符（需 ## slide-N 分段）"

  local base="${ppt%.pptx}"            # 含路徑的主檔名
  local name="$(basename "$base")"      # 純檔名
  local dir="$(dirname "$ppt")"         # 輸出目錄 = PPT 所在目錄
  local safe="$(sanitize "$name")"      # 安全目錄名
  local pipe_script="$dir/${safe}-narration-script.md"
  local out_dir="$dir/_narration_${safe}"
  # 輸入若已是「-講稿版」，輸出檔名不要再疊一層（…-講稿版-講稿版.pptx）
  local out_base="${base%-講稿版}"
  local notes_pptx="$out_base-講稿版.pptx"
  local voice_pptx="$out_base-配音版.pptx"

  # 1. 講稿 → pipeline 專用稿（剝離講師提示/附錄/markdown 語法）
  info "1/4 轉換 pipeline 講稿 → ${pipe_script##*/}"
  "$PYTHON" - "$script_md" "$pipe_script" <<'PYEOF'
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

  # 2. 跑 narrate-pipeline（逐段 TTS + 拼接 + timeline）
  info "2/4 TTS 配音（17 段約需 2-5 分鐘）"
  node "$PIPELINE" --script "$pipe_script" --out-dir "$out_dir" || die "narrate-pipeline 失敗"

  # 3+4. 講稿寫入備註 → 講稿版; 音訊嵌入 → 配音版
  info "3/4 產生講稿版 + 配音版 PPTX"
  "$PYTHON" - "$ppt" "$script_md" "$out_dir" "$notes_pptx" "$voice_pptx" <<'PYEOF'
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

# ── 講稿 → 備註 ──
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

# ── 音訊嵌入（基於講稿版）──
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

  # 完成
  local total
  total=$("$PYTHON" -c "
import json, sys
t = json.load(open(sys.argv[1]))
print(f'{t[\"totalDuration\"]/60:.1f} 分鐘')
" "$out_dir/timeline.json")
  ok "全部完成！總配音時長 ${total}"
  echo ""
  echo "📄 ${notes_pptx##*/}   （講稿備註版）"
  echo "🎧 ${voice_pptx##*/}   （配音版：每頁右下角喇叭點擊播放）"
  echo "🗣 $out_dir/voiceover.mp3  （整段配音 ${total}）"
}

# ── 主流程 ─────────────────────────────────────────────────────────────────
[ $# -ge 2 ] || { sed -n '3,16p' "$0"; exit 1; }
check_env
case "$1" in
  extract) cmd_extract "$2" ;;
  build)   [ $# -ge 3 ] || die "用法: $0 build <ppt> <script.md>"; cmd_build "$2" "$3" ;;
  *) die "未知子命令: $1（可用 extract / build）" ;;
esac
