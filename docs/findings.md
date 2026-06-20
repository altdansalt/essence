# Findings

Empirical observations from building and running the loop.

## F1 — exe.dev Fireworks gateway path

The documented low-level gateway is `http://169.254.169.254/gateway/llm/<provider>`.
For Fireworks, `/v1/chat/completions` returns `NOT_FOUND`. The working path
includes `/inference`:

```
http://169.254.169.254/gateway/llm/fireworks/inference/v1/chat/completions
```

Anthropic (`/gateway/llm/anthropic/v1/messages`) and OpenAI
(`/gateway/llm/openai/v1/chat/completions`, note: use
`max_completion_tokens` not `max_tokens` for newer models) work directly.

## F2 — GLM-5.2 reasoning behavior (the big one)

- Without `reasoning_effort`, GLM-5.2 emits long *visible* chain-of-thought and
  frequently exhausts `max_tokens` before emitting any code, even with
  explicit "output only a code fence" system prompts. On a ~8.8k-token source
  it produced 400 bytes of stubs at `max_tokens=8000`, and 100 bytes at 16000,
  and still no code at 24000.
- With `reasoning_effort: "low"|"medium"|"high"`, reasoning goes to a hidden
  channel and the visible output is clean fenced code with `finish_reason=stop`.
  For the full SQLite port, `low` yielded a ~5.2k-token Python port that parses
  and runs correctly.
- `chat_template_kwargs: {enable_thinking: false}` is **not** supported by the
  gateway (`Extra inputs are not permitted`).
- Conclusion: always set `reasoning_effort` for GLM-5.2 code generation.

## F3 — The C reference had a real bug

The first cut of `sqlite_core.c` lexed every keyword as a plain identifier
because `is_kw` compared a non-NUL-terminated source slice with `strcasecmp`,
which fails when the slice is followed by more SQL text. Fixed with an
explicit `is_kw_n(s, len)` using `strncasecmp`. The reference now compiles,
runs CREATE/INSERT/SELECT/WHERE/ORDER BY/INNER JOIN, and its demo output is
the contract.

## F4 — Judge needs the full port

Truncating the port to 16k chars before judging made Haiku call a complete
580-line Python port "truncated" (completeness 42). With the full port
visible, the same port scored 78 with accurate, specific notes. Haiku 4.5 has
a 200k context — feed it the whole port.

## F5 — First real result: Python

- Original C: 8805 tokens, 712 lines.
- Python port: ~5200 tokens, 580 lines. **Runs correctly**, demo output
  matches the C reference (`3 | linus` / `2 | grace`).
- Judge completeness: 78. Reduction factor: ~1.69x.

Python is concise but not dramatically smaller than C here because the C
reference is already fairly tight and the port is fairly literal. We expect
bigger reductions from ML-family and typed-functional languages (Haskell,
OCaml, Erlang, etc.).

## F6 — Language list

`tools/crawl_lxim.py` harvests 138 programming languages from the
learnxinyminutes-docs repo after filtering out tools, frameworks, data
formats, and uppercase meta-files (README/CONTRIBUTING). Categories in the
frontmatter are sparse (only ~40 of 199 files declare one), so the filter is
mostly an explicit slug denylist plus an uppercase-slug rule.

## F7 — First batch (top 8 by promise_score)

| language | completeness | reduction | port_tok | finish |
|----------|-------------|-----------|----------|--------|
| Python   | 78 | 1.69x | 5200 | stop |
| Java     | 78 | 1.43x | 6175 | (n/a) |
| Rust     | 72 | 1.29x | 6805 | (n/a) |
| C#       | 72 | 1.27x | 6931 | (n/a) |
| Haxe     | 72 | 1.23x | 7182 | (n/a) |
| Nostos   | 42 | 1.35x | 6506 | stop |
| F#       | 32 | 1.4x  | 6298 | stop |
| Odin     | 15 | n/a   | 136  | length (capped even at 32k + high retry) |
| Vim9     |  8 | n/a   | 132  | length (capped) |

Observations:
- The mainstream object-oriented / systems languages (Python, Java, Rust, C#,
  Haxe) all produced complete ports (72–78) with modest reductions (1.2–1.7x).
  The C reference is already fairly tight, so reductions are bounded.
- GLM-5.2 is **non-deterministic**: the first F# run (16k cap) gave stubs;
  re-run at 32k gave completeness 72, then a third run gave 32. Same prompt,
  same params. We should treat single-shot scores as noisy and consider
  multiple samples for the languages that matter.
- Some languages defeat the porter entirely: Odin and Vim9 script hit
  `finish_reason=length` even at `max_tokens=32000` with `reasoning_effort=high`,
  producing ~130-token stubs. These are signals that the language is either
  unfamiliar to GLM-5.2 or a poor fit for one-shot porting of a structured
  engine. The leaderboard marks these `n/a` rather than reporting a bogus 64x
  reduction.
- `reasoning_effort=low` + `max_tokens=32000` + length-cap retry is the
  working configuration. Most languages finish with `stop` in 60–170s.

## F8 — The leaderboard's "reduction" must be read with completeness

A 130-token stub is a 66x "reduction" but is useless. The leaderboard now
flags `finish_reason=length` or `completeness<30` as `n/a` with a ⚠️. The
ranking sorts by completeness first, so stubs sink to the bottom.
