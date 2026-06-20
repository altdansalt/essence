#!/usr/bin/env python3
"""Crawl languages from https://learnxinyminutes.com/.

The site is generated from a markdown repo (adambard/learnxinyminutes-docs).
Each language file has YAML-ish frontmatter with `name:` and an optional
`category:`. Categories are sparse (most language files have none), so we use
a hybrid heuristic:

  INCLUDE a file as a "language" if:
    - it is a .md file under the repo, AND
    - it is not README/CONTRIBUTING/LICENSE, AND
    - its category (if present) is NOT in the exclude set
      {tool, framework, Algorithms & Data Structures, data formats,
      Algorithms,Data Structures}, AND
    - its slug is not in an explicit denylist of known non-languages
      (coq, verilog, opencl, ... are kept as languages; formats/tools excluded).

We also extract a short "promise" signal from the file: does it mention types,
generics, pattern matching, etc. — used later to rank by likely reduction.

Output: JSON to stdout (or --out FILE) with a list of
  {slug, name, category, path, lines, promise_score}

Usage:
    crawl_lxim.py [--repo DIR] [--out FILE]
If --repo is omitted, clones adambard/learnxinyminutes-docs to a tempdir.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

REPO_URL = "https://github.com/adambard/learnxinyminutes-docs.git"

# Categories that are NOT programming languages.
EXCLUDE_CATEGORIES = {
    "tool", "framework",
    "Algorithms & Data Structures",
    "Algorithms", "Data Structures",
    "data formats", "data format",
}

# Slugs that are docs/formats/tools even though they read like languages.
EXCLUDE_SLUGS = {
    "readme", "contributing", "license",
    "asciidoc", "yaml", "json", "toml", "csv", "xml", "html", "css",
    "markdown", "regular-expressions", "regexp", "regex",
    "cmake", "make", "nix", "dhall", "cue", "json5", "hocon",
    "pug", "sass", "scss", "less", "stylus", "haml",
    "graphql", "openapi", "protobuf", "thrift",
    "latex", "tex", "bibtex",
    "mathematica",  # CAS, not a general language for porting
    "emacs-lisp",   # keep? it's a lisp -> include. remove from exclude.
}
EXCLUDE_SLUGS.discard("emacs-lisp")
EXCLUDE_SLUGS.discard("common-lisp")

# Signals that suggest a language can express a compact port (higher = more promise).
PROMISE_PATTERNS = [
    (r"\bgenerics?\b", 2),
    (r"\bpattern matching\b", 2),
    (r"\balgebraic data types?\b|\bADTs?\b", 2),
    (r"\bfirst-?class functions?\b", 1),
    (r"\bclosures?\b", 1),
    (r"\btype inference\b", 1),
    (r"\bmacros?\b", 1),
    (r"\bstructs?\b|\brecords?\b", 1),
    (r"\bclasses?\b|\bobjects?\b", 1),
    (r"\binterfaces?\b|\btraits?\b", 1),
    (r"\biterators?\b|\bgenerators?\b", 1),
    (r"\bmodules?\b|\bpackages?\b", 1),
    (r"\bgarbage collection\b|\bGC\b", 1),
    (r"\bcompiled\b", 1),
    (r"\bbytecode\b|\bVM\b", 1),
]


def frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not m:
        return {}
    fm = m.group(1)
    out = {}
    for line in fm.splitlines():
        m2 = re.match(r"^([a-zA-Z_]+):\s*(.*)$", line)
        if m2:
            out[m2.group(1)] = m2.group(2).strip().strip('"\'')
    return out


def promise_score(text: str) -> int:
    score = 0
    for pat, w in PROMISE_PATTERNS:
        if re.search(pat, text, re.I):
            score += w
    return score


def is_language(slug: str, fm: dict) -> bool:
    # README/CONTRIBUTING/LICENSE etc. use UPPERCASE slugs; real language slugs are lowercase.
    if slug != slug.lower():
        return False
    if slug in EXCLUDE_SLUGS:
        return False
    cat = fm.get("category", "").strip()
    if cat in EXCLUDE_CATEGORIES:
        return False
    return True


def crawl(repo: str) -> list[dict]:
    out = []
    for fn in sorted(os.listdir(repo)):
        if not fn.endswith(".md"):
            continue
        slug = fn[:-3]
        path = os.path.join(repo, fn)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        fm = frontmatter(text)
        if not is_language(slug, fm):
            continue
        name = fm.get("name", slug).strip()
        lines = text.count("\n") + 1
        out.append({
            "slug": slug,
            "name": name,
            "category": fm.get("category", ""),
            "path": path,
            "lines": lines,
            "promise_score": promise_score(text),
        })
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="path to a clone of learnxinyminutes-docs")
    ap.add_argument("--out", help="write JSON here instead of stdout")
    args = ap.parse_args(argv)

    repo = args.repo
    tmpdir = None
    if not repo:
        tmpdir = tempfile.mkdtemp(prefix="lxim-")
        repo = os.path.join(tmpdir, "learnxinyminutes-docs")
        print(f"cloning {REPO_URL} -> {repo}", file=sys.stderr)
        r = subprocess.run(["git", "clone", "--depth", "1", REPO_URL, repo],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"clone failed: {r.stderr}", file=sys.stderr)
            return 1
    try:
        langs = crawl(repo)
    finally:
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
    data = json.dumps(langs, indent=2, ensure_ascii=False)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(data + "\n")
        print(f"wrote {len(langs)} languages to {args.out}", file=sys.stderr)
    else:
        print(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
