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
