#!/usr/bin/env python3
"""essence porting loop.

For each target language (one at a time), in priority order:

  1. Build a porter prompt: the SQLite core contract + the language's
     learnxinyminutes cheatsheet + instructions to port.
  2. Call the porter agent (GLM-5.2 on Fireworks via the exe.dev gateway).
  3. Extract the ported source from the response.
  4. Token-count the original (sqlite_core.c) and the port.
  5. Call a separate judge agent (Claude Haiku 4.5) to score completeness.
  6. Record everything under runs/<lang>/ and update the leaderboard
     (LANGUAGES.md) and findings.
  7. Commit and push.

Usage:
    loop.py [--limit N] [--only slug] [--no-push]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import llm  # noqa: E402
import token_count as tc  # noqa: E402

SOURCE_C = os.path.join(ROOT, "source", "sqlite_core.c")
SOURCE_TEST = os.path.join(ROOT, "source", "sqlite_core.test.sql")
LANGUAGES_JSON = os.path.join(ROOT, "languages.json")
RUNS_DIR = os.path.join(ROOT, "runs")
LOGS_DIR = os.path.join(ROOT, "logs")

PORTER_SYS = """You are an expert polyglot software engineer porting a C codebase to another programming language.
You port faithfully and completely: every public function, every behavior, every SQL feature supported by the source must appear in the port.
You prefer idiomatic code in the target language, using that language's strengths to be as concise as possible while preserving behavior.

CRITICAL OUTPUT RULE: Do NOT show your reasoning. Do NOT write "Let me...", "I will...", or any analysis. Your ENTIRE output must be a single markdown code fence containing the complete ported source file. The opening ``` fence must be the first characters you emit. No prose before or after the fence. If you need to think, think briefly and then output ONLY the code fence."""

def load_languages() -> list[dict]:
    return json.load(open(LANGUAGES_JSON, encoding="utf-8"))

def lxim_path(lang: dict) -> str | None:
    p = lang.get("path")
    return p if p and os.path.exists(p) else None

def porter_prompt(lang: dict) -> list[dict]:
    src = open(SOURCE_C, encoding="utf-8").read()
    cheatsheet = ""
    p = lxim_path(lang)
    if p:
        cheatsheet = open(p, encoding="utf-8", errors="replace").read()
        # cap cheatsheet size to keep prompt bounded
        if len(cheatsheet) > 20000:
            cheatsheet = cheatsheet[:20000] + "\n... (truncated)\n"
    user = f"""Port the following compact SQLite-style SQL engine (written in C) to {lang['name']} ({lang['slug']}).

Target language: {lang['name']}
Use the language cheatsheet below as a syntax reference.

Requirements:
- Implement the SAME public API surface: open, exec (with callback), prepare_v2, step, finalize, close, column_count, column_text, column_int64, errmsg. Name them as idiomatic for {lang['name']} (e.g. a class/module Sqlite3 with methods open/exec/prepare/step/finalize/close) but keep the same behavior.
- Implement the SAME SQL subset: CREATE TABLE, INSERT ... VALUES, SELECT with projections, SELECT *, WHERE (with =,<>,<,>,<=,>=, AND, OR), ORDER BY ... [DESC|ASC], and INNER JOIN ... ON.
- Implement the same architecture: lexer, parser, executor, in-memory table store. You may merge layers if the language makes it more concise, but behavior must match.
- Values are NULL / integer / text. Comparisons and ordering must match the C reference.
- Include a runnable demo `main`/entry equivalent to the C `SQLITE_CORE_DEMO` block that prints the SELECT results.
- Be as concise as the language allows. Minimize boilerplate. Use the language's best features (pattern matching, comprehensions, algebraic types, etc.) to shrink the code.

### C reference source (sqlite_core.c) -- the contract:
```c
{src}
```

### {lang['name']} cheatsheet (learnxinyminutes):
```
{cheatsheet}
```

Now output the full port to {lang['name']} in a single fenced code block. Nothing else."""
    return [{"role": "system", "content": PORTER_SYS}, {"role": "user", "content": user}]

def run_porter(lang: dict, *, max_tokens: int = 32000) -> tuple[str, dict, str, float, str]:
    """Returns (ported_code, usage, raw_response, elapsed, finish_reason).

    If GLM-5.2 hits the length cap (finish_reason=='length'), retry once with
    reasoning_effort='high' and a larger budget; that usually means the model
    needs more thinking room to produce complete code in one pass.
    """
    msgs = porter_prompt(lang)
    t0 = time.time()
    resp = llm.porter(msgs, max_tokens=max_tokens, temperature=0.3)
    finish = resp.get("choices", [{}])[0].get("finish_reason", "")
    usage = resp.get("usage", {})
    raw = resp["choices"][0]["message"]["content"]
    if finish == "length":
        log(f"      porter length-capped ({usage.get('completion_tokens')} tok); retry high effort")
        resp2 = llm.porter(msgs, max_tokens=max_tokens, temperature=0.3, reasoning_effort="high")
        finish2 = resp2.get("choices", [{}])[0].get("finish_reason", "")
        raw2 = resp2["choices"][0]["message"]["content"]
        # prefer the retry if it produced a longer fenced code block
        if len(llm.extract_code(raw2)) > len(llm.extract_code(raw)):
            raw, usage, finish = raw2, resp2.get("usage", {}), finish2
    elapsed = time.time() - t0
    code = llm.extract_code(raw)
    return code, usage, raw, elapsed, finish

def judge(lang: dict, ported_code: str, *, max_tokens: int = 2000) -> tuple[dict, str, dict]:
    """Run the judge agent. Returns (score_dict, judge_text, usage)."""
    src = open(SOURCE_C, encoding="utf-8").read()
    system = """You are a strict but fair judge evaluating a code port for completeness.
You will be given the original C source and a port to another language.
Score the port on COMPLETENESS ONLY (not whether it compiles or runs, which we cannot verify here).
Return STRICT JSON only, no prose, with this shape:
{"completeness": <0-100 integer>, "api_surface": <0-100>, "sql_features": <0-100>, "architecture": <0-100>, "notes": "<one or two sentences>"}"""
    user = f"""Original C source (sqlite_core.c):
```c
{src}
```

Ported source ({lang['name']}):
```
{ported_code}
```

Score the port. The original implements: sqlite3_open/exec/prepare_v2/step/finalize/close, column_count/column_text/column_int64/errmsg; SQL: CREATE TABLE, INSERT VALUES, SELECT with projections, SELECT *, WHERE (=,<>,<,>,<=,>=,AND,OR), ORDER BY [DESC|ASC], INNER JOIN ON; values NULL/int/text; a demo main.
Return JSON now."""
    text, usage = llm.judge_text([{"role": "user", "content": user}], max_tokens=max_tokens, system=system)
    score = parse_judge(text)
    return score, text, usage

def parse_judge(text: str) -> dict:
    # find first {...} block
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"completeness": 0, "notes": "judge returned no JSON", "_raw": text[:500]}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {"completeness": 0, "notes": "judge JSON parse failed", "_raw": text[:500]}

def record_run(lang: dict, ported_code: str, port_tokens: int, orig_tokens: int,
               porter_usage: dict, judge_score: dict, judge_usage: dict,
               elapsed: float, raw_porter: str, raw_judge: str,
               finish: str = "") -> str:
    slug = lang["slug"]
    rundir = os.path.join(RUNS_DIR, slug)
    os.makedirs(rundir, exist_ok=True)
    # write ported code: guess extension
    ext = guess_ext(lang["slug"])
    code_path = os.path.join(rundir, f"sqlite_core.{ext}")
    open(code_path, "w", encoding="utf-8").write(ported_code)
    meta = {
        "language": lang["name"],
        "slug": slug,
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "elapsed_seconds": round(elapsed, 1),
        "porter_finish_reason": finish,
        "original_tokens": orig_tokens,
        "ported_tokens": port_tokens,
        "token_ratio": round(port_tokens / orig_tokens, 4) if orig_tokens else None,
        "reduction_factor": round(orig_tokens / port_tokens, 2) if port_tokens else None,
        "porter_model": llm.PORTER_MODEL,
        "judge_model": llm.JUDGE_MODEL,
        "porter_usage": porter_usage,
        "judge_usage": judge_usage,
        "judge_score": judge_score,
    }
    open(os.path.join(rundir, "meta.json"), "w").write(json.dumps(meta, indent=2) + "\n")
    open(os.path.join(rundir, "porter_raw.txt"), "w").write(raw_porter)
    open(os.path.join(rundir, "judge_raw.txt"), "w").write(raw_judge)
    return rundir

EXTS = {
    "python":"py","py":"py","ruby":"rb","javascript":"js","typescript":"ts","js":"js",
    "go":"go","rust":"rs","haskell":"hs","ocaml":"ml","fsharp":"fs","csharp":"cs",
    "java":"java","kotlin":"kt","scala":"scala","swift":"swift","dart":"dart",
    "elixir":"ex","erlang":"erl","clojure":"clj","lisp":"lisp","common-lisp":"lisp",
    "scheme":"scm","racket":"rkt","lua":"lua","perl":"pl","raku":"raku","php":"php",
    "crystal":"cr","nim":"nim","julia":"jl","j":"ijs","apl":"apl","bqn":"bqn",
    "zig":"zig","odin":"odin","v":"v","d":"d","ada":"adb","fortran":"f90",
    "cobol":"cbl","pascal":"pas","delphi":"pas","elm":"elm","purescript":"purs",
    "gleam":"gleam","roc":"roc","grain":"gr","vlang":"v","wren":"wren",
    "lua":"lua","tcl":"tcl","bash":"sh","awk":"awk","r":"r","julia":"jl","matlab":"m",
    "wolfram":"wls","julia":"jl","carbon":"carbon","mojo":"mojo","nim":"nim",
}
def guess_ext(slug: str) -> str:
    if slug in EXTS: return EXTS[slug]
    return "txt"

def git(*args: str, check: bool = True) -> int:
    return subprocess.run(["git", *args], cwd=ROOT, check=check).returncode

def commit_push(msg: str, push: bool) -> None:
    git("add", "-A")
    r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if r.returncode == 0:
        print("  (nothing to commit)")
        return
    git("commit", "-m", msg)
    if push:
        git("push")

def log(msg: str) -> None:
    line = f"[{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}"
    print(line, flush=True)
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(os.path.join(LOGS_DIR, "loop.log"), "a") as f:
        f.write(line + "\n")

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max languages to process (0=all)")
    ap.add_argument("--only", help="only run this slug")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--max-tokens", type=int, default=16000)
    args = ap.parse_args(argv)

    langs = load_languages()
    # sort by promise score desc, then name
    langs.sort(key=lambda l: (-l.get("promise_score", 0), l["name"]))
    if args.only:
        langs = [l for l in langs if l["slug"] == args.only]
        if not langs:
            print(f"no language matching slug {args.only}", file=sys.stderr)
            return 2
    if args.limit:
        langs = langs[:args.limit]

    orig_tokens, _, _ = tc.count_path(SOURCE_C)
    log(f"loop start: {len(langs)} languages, orig_tokens={orig_tokens}")

    done = 0
    for lang in langs:
        slug = lang["slug"]
        rundir = os.path.join(RUNS_DIR, slug)
        meta_path = os.path.join(rundir, "meta.json")
        if os.path.exists(meta_path):
            log(f"  skip {slug}: already has a run")
            continue
        log(f"  >>> porting {slug} ({lang['name']})")
        try:
            code, porter_usage, raw_porter, elapsed, finish = run_porter(lang, max_tokens=args.max_tokens)
            port_tokens, _, _ = tc.count_text(code), 0, 0
            port_tokens = tc.count_text(code)
            log(f"      porter done: {len(code)} bytes, {port_tokens} tokens, {elapsed:.1f}s")
            score, raw_judge, judge_usage = judge(lang, code)
            comp = score.get("completeness", 0)
            log(f"      judge: completeness={comp} notes={score.get('notes','')[:80]}")
            record_run(lang, code, port_tokens, orig_tokens,
                        porter_usage, score, judge_usage, elapsed, raw_porter, raw_judge,
                        finish)
            done += 1
            commit_push(f"port: {slug} ({lang['name']}) completeness={comp}", not args.no_push)
        except Exception as e:
            log(f"      ERROR on {slug}: {e}")
            log(traceback.format_exc())
            # record a failure marker so we don't retry endlessly
            os.makedirs(rundir, exist_ok=True)
            open(os.path.join(rundir, "ERROR.txt"), "w").write(f"{e}\n{traceback.format_exc()}")
            commit_push(f"port: {slug} failed: {e}", not args.no_push)
            continue
    log(f"loop done: {done} runs")
    # rebuild leaderboard
    try:
        rebuild_leaderboard()
        commit_push("update leaderboard (LANGUAGES.md)", not args.no_push)
    except Exception as e:
        log(f"leaderboard rebuild failed: {e}")
    return 0

def rebuild_leaderboard() -> None:
    """Scan runs/*/meta.json and write LANGUAGES.md sorted by completeness then reduction."""
    rows = []
    for slug in sorted(os.listdir(RUNS_DIR)):
        mp = os.path.join(RUNS_DIR, slug, "meta.json")
        if not os.path.exists(mp): continue
        m = json.load(open(mp))
        rows.append(m)
    # sort: completeness desc, then reduction_factor desc
    rows.sort(key=lambda r: (-(r.get("judge_score",{}).get("completeness",0) or 0),
                             -(r.get("reduction_factor") or 0)))
    out = ["# Language leaderboard", "",
           "Sorted by judge completeness, then reduction factor (orig_tokens/port_tokens).",
           "Reduction >1 means the port is smaller than the C reference by token count.",
           "",
           "| # | language | completeness | reduction | port/orig tokens | notes |",
           "|---|----------|-------------|-----------|------------------|-------|"]
    for i, r in enumerate(rows, 1):
        js = r.get("judge_score", {})
        out.append(f"| {i} | {r['language']} | {js.get('completeness','-')} | "
                   f"{r.get('reduction_factor','-')}x | {r.get('ported_tokens','-')}/{r.get('original_tokens','-')} | "
                   f"{(js.get('notes','') or '').replace('|','\\|')[:80]} |")
    out.append("")
    open(os.path.join(ROOT, "LANGUAGES.md"), "w").write("\n".join(out))

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
