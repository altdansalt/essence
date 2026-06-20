# Decisions

A running log of design decisions and why.

## D1 — Target: bounded SQLite core, not the full amalgamation

The real SQLite amalgamation (`sqlite3.c`) is ~257k lines / ~9 MB. That is far
beyond a single LLM context window, so it cannot be ported in one pass and
"reduction" would be measured against an input the model never fully saw.

Instead we wrote `source/sqlite_core.c`: a compact (~700 line, ~8.8k token)
in-memory SQLite-style SQL engine that implements a recognizable slice of
SQLite's architecture (lexer → parser → executor → in-memory store → public
`sqlite3_*` API). It compiles, runs, and its demo output is the contract every
port tries to reproduce. This keeps every language port on the **same input**
and the **same yardstick**.

See `docs/roads-not-taken.md` for the full reasoning and alternatives.

## D2 — Porter model: GLM-5.2 on Fireworks via the exe.dev gateway

As specified. The exe.dev LLM gateway authenticates the VM, so no API keys are
needed. The Fireworks endpoint is
`http://169.254.169.254/gateway/llm/fireworks/inference/v1/chat/completions`
(note the `/inference` segment — the bare `/v1/chat/completions` path returns
NOT_FOUND; see `docs/findings.md`).

## D3 — `reasoning_effort=low` for the porter (critical)

GLM-5.2 has a strong chain-of-thought habit. On large generation tasks it
emits *visible* reasoning ("Let me port ... I need to implement ...") and burns
the entire `max_tokens` budget on prose, never emitting the code fence. Setting
`reasoning_effort: "low"` (a Fireworks chat-completions param) routes that
thinking into a **hidden channel**, so the visible output is clean fenced code
and `finish_reason` is `stop`. This was the single biggest fix; without it the
loop produced only stubs. Default is configurable via `PORTER_REASONING`.

## D4 — Judge model: Claude Haiku 4.5 (separate agent)

A different model from the porter, so the judge isn't grading its own work.
Haiku 4.5 is cheap ($1/$5 per Mtok) and sharp enough for structured
completeness scoring. We score **completeness only** (not compile/run, which
we can't verify across 138 languages). Scores: `completeness` (0–100) plus
sub-scores for `api_surface`, `sql_features`, `architecture`, and notes.

## D5 — Token yardstick: tiktoken `cl100k_base`

A stable, model-agnostic tokenizer. We count the original C source and every
port with the *same* encoder so `orig_tokens / port_tokens` (the reduction
factor) is comparable across languages. Token counts are not line counts; they
better reflect "how much information."

## D6 — One language at a time, one shot each

No parallel ports, no multi-turn refinement yet. Sequential, deterministic,
commit-after-each. This keeps the experiment clean and the repo a faithful
log. Re-running a language is idempotent (the loop skips slugs that already
have `runs/<slug>/meta.json`).

## D7 — Ranking: completeness first, then reduction

A tiny but incomplete port is not a "win." The leaderboard sorts by judge
`completeness` descending, then by reduction factor descending. This surfaces
languages that both preserve behavior *and* shrink the code.

## D8 — Cheatsheet as syntax reference

Each porter prompt includes that language's learnxinyminutes cheatsheet
(capped at 20k chars) as a syntax reference. This nudges the porter toward
idiomatic code in languages it may know less well.
