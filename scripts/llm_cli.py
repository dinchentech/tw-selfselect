#!/usr/bin/env python3
"""scripts/llm_cli.py — 把「任何模型」包成 AI 選股 A/B 需要的 CLI（stdin→stdout 純 JSON）

## 這是什麼

`scripts/ai_pick_ab.py` 的 `--llm-cmd` 只要求一件事：

    **從 stdin 讀 prompt、把 JSON 印到 stdout（其他什麼都不要印）、成功時 exit 0。**

本檔就是那個「轉接頭」：它幫你呼叫模型，並把回應清理成純 JSON。支援：

| provider | 用途 | 需要的環境變數 |
|---|---|---|
| `openai` | 任何 **OpenAI 相容** API（OpenAI／DeepSeek／OpenRouter／自架 vLLM…） | `OPENAI_API_KEY`（必）、`OPENAI_BASE_URL`（選，預設官方）、`LLM_MODEL`（必） |
| `ollama` | 本機 Ollama（不花錢、不連外） | `LLM_MODEL`（必，例如 `qwen2.5:14b`）、`OLLAMA_HOST`（選，預設 127.0.0.1:11434） |
| `echo` | **不呼叫模型**，把固定答案印出來（測試管線用；不是真的選股） | 無 |

## 用法（接進 A/B）

    # 本機 Ollama
    .venv/bin/python scripts/ai_pick_ab.py --start 2022-01-01 --end 2022-12-31 --top-n 5 \
      --llm-cmd ".venv/bin/python scripts/llm_cli.py --provider ollama --model qwen2.5:14b"

    # OpenAI 相容（金鑰只放環境變數，不進 repo）
    export OPENAI_API_KEY=... OPENAI_BASE_URL=https://api.deepseek.com/v1 LLM_MODEL=deepseek-chat
    .venv/bin/python scripts/ai_pick_ab.py ... --llm-cmd ".venv/bin/python scripts/llm_cli.py --provider openai"

    # 先測管線（不會花錢）
    .venv/bin/python scripts/ai_pick_ab.py ... --llm-cmd ".venv/bin/python scripts/llm_cli.py --provider echo"

## 契約（很重要）

- **stdout 只能有 JSON**：模型愛包 ```json 圍欄或多說一句話，本檔會自動抽出第一個完整 JSON 物件；
  真的抽不到就 exit 2（A/B 會把那天記成「模型輸出不合格」）。
- 不串流（一次拿完）、`temperature` 預設 0（同一輸入盡量同一輸出，才可重現）。
- **本檔不存任何金鑰、不寫 log 到專案外**；prompt 由 A/B／preview 端負責落地稽核。
"""
import argparse
import json
import os
import sys


def extract_json(text: str):
    """從模型輸出抽出第一個完整的 JSON 物件（容忍 ```json 圍欄／前後多餘文字）。

    找不到 → 丟 `ValueError`（呼叫端會 exit 2）。
    """
    if text is None:
        raise ValueError("空回應")
    s = text.strip()
    if s.startswith("```"):
        parts = s.split("```")
        for p in parts:
            body = p.strip()
            if body.startswith("json"):
                body = body[4:].strip()
            if body.startswith("{"):
                s2 = body
                try:
                    return json.loads(s2)
                except Exception:
                    continue
    depth = 0
    start = None
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                cand = s[start:i + 1]
                try:
                    return json.loads(cand)
                except Exception:
                    start = None
    raise ValueError("找不到合法 JSON 物件")


def _call_openai(prompt: str, model: str, base: str | None, temperature: float) -> str:
    import requests

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("缺少 OPENAI_API_KEY（只放環境變數，不要寫進 .env.example 以外的檔案）")
    base = (base or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    r = requests.post(f"{base}/chat/completions",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model, "temperature": temperature,
                            "messages": [{"role": "user", "content": prompt}]},
                      timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
    d = r.json()
    return d["choices"][0]["message"]["content"]


def _call_ollama(prompt: str, model: str, host: str | None, temperature: float) -> str:
    import requests

    host = (host or os.getenv("OLLAMA_HOST") or "127.0.0.1:11434").replace("http://", "").rstrip("/")
    r = requests.post(f"http://{host}/api/chat",
                      json={"model": model, "stream": False, "options": {"temperature": temperature},
                            "messages": [{"role": "user", "content": prompt}]},
                      timeout=600)
    if r.status_code != 200:
        raise RuntimeError(f"Ollama {r.status_code}: {r.text[:300]}")
    return r.json().get("message", {}).get("content", "")


def _call_echo(prompt: str, model: str, host: str | None, temperature: float) -> str:
    """不呼叫模型：把 prompt 裡的 [R#] 代號照順序取前 N 檔（只驗管線）。"""
    import re
    m = re.search(r"選出 (\d+) 檔", prompt)
    top = int(m.group(1)) if m else 5
    found = re.findall(r"\[R(\d+)\] ([0-9A-Za-z]+)", prompt)
    as_of = re.search(r"選股日：(\S+)", prompt)
    return json.dumps({"as_of": as_of.group(1) if as_of else "",
                       "picks": [{"sid": sid, "reasons": [f"echo 測試 [R{rn}]"], "citations": [f"R{rn}"]}
                                 for rn, sid in found[:top]]}, ensure_ascii=False)


PROVIDERS = {"openai": _call_openai, "ollama": _call_ollama, "echo": _call_echo}


def main():
    ap = argparse.ArgumentParser(description="把 prompt(stdin) 轉成模型回應(JSON/stdout)")
    ap.add_argument("--provider", choices=sorted(PROVIDERS), default="ollama")
    ap.add_argument("--model", default=os.getenv("LLM_MODEL", ""), help="模型名稱（或設 LLM_MODEL）")
    ap.add_argument("--base-url", default=None, help="OpenAI 相容 API 的 base（或設 OPENAI_BASE_URL）")
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args()

    prompt = sys.stdin.read()
    if not prompt.strip():
        print("❌ stdin 是空的（要從 A/B 或 preview 餵 prompt 進來）", file=sys.stderr)
        return 2
    if args.provider != "echo" and not args.model:
        print("❌ 缺少 --model（或環境變數 LLM_MODEL）", file=sys.stderr)
        return 2
    try:
        raw = PROVIDERS[args.provider](prompt, args.model or "(echo)", args.base_url, args.temperature)
    except Exception as e:
        print(f"❌ 模型呼叫失敗：{e}", file=sys.stderr)
        return 1
    try:
        obj = extract_json(raw)
    except ValueError as e:
        print(f"❌ 回應裡找不到 JSON（{e}）", file=sys.stderr)
        return 2
    print(json.dumps(obj, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
