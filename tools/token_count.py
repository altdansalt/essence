#!/usr/bin/env python3
"""Token counting for essence.

Uses tiktoken's cl100k_base as a stable, model-agnostic approximation of
"how much text is this". We count both the original source and each port so
reduction ratios are comparable on the same yardstick.

Usage:
    token_count.py <path>           # print token count for a file or dir
    token_count.py --ratio A B      # print B/A token ratio
"""
from __future__ import annotations

import os
import sys
import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


def count_text(s: str) -> int:
    return len(_ENC.encode(s, disallowed_special=()))


def count_path(path: str) -> tuple[int, int, int]:
    """Return (tokens, bytes, lines) for a file or recursively for a dir."""
    toks = bytes_ = lines = 0
    if os.path.isdir(path):
        for root, _dirs, files in os.walk(path):
            for fn in files:
                p = os.path.join(root, fn)
                t, b, l = _count_file(p)
                toks += t; bytes_ += b; lines += l
    else:
        toks, bytes_, lines = _count_file(path)
    return toks, bytes_, lines


def _count_file(p: str) -> tuple[int, int, int]:
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            s = f.read()
    except OSError:
        return 0, 0, 0
    return count_text(s), len(s.encode("utf-8", errors="replace")), s.count("\n") + (0 if not s else 0)


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--ratio":
        if len(argv) < 3:
            print("usage: token_count.py --ratio A B", file=sys.stderr)
            return 2
        a = count_path(argv[1])[0]
        b = count_path(argv[2])[0]
        if a == 0:
            print("div-by-zero")
            return 1
        print(f"{b / a:.4f}")
        print(f"orig_tokens={a} port_tokens={b}")
        return 0
    if not argv:
        print("usage: token_count.py <path> | --ratio A B", file=sys.stderr)
        return 2
    t, b, l = count_path(argv[0])
    print(f"tokens={t} bytes={b} lines={l} path={argv[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
