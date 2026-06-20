# Roads not taken

Alternatives considered and rejected, with reasons.

## RT1 — Port the full SQLite amalgamation directly

**Considered:** feed the 257k-line `sqlite3.c` to the porter.
**Rejected:** far beyond any single LLM context. A faithful one-shot port is
impossible, and "reduction" would be measured against an input the model never
saw. Would require chunked/multi-pass porting, which conflates "language
conciseness" with "how well the model stitches chunks."

## RT2 — Use a different porter model

**Considered:** a less verbose model (e.g. Claude or GPT) as the porter.
**Rejected:** the task explicitly specifies GLM-5.2 on Fireworks via the
gateway. We kept GLM-5.2 and worked around its verbosity with
`reasoning_effort=low` (D3). If GLM-5.2 underperforms on a language, we can
retry with `medium`/`high` effort or a higher `max_tokens`.

## RT3 — Require ports to compile and pass tests

**Considered:** install each language's toolchain and run `sqlite_core.test.sql`
against every port.
**Rejected (for now):** 138 languages means ~138 toolchains; many are exotic
(Ada, Coq, BQN, APL, BF). The task says ports don't have to run. We score
completeness via a judge instead. Verifying compilation is a natural next
phase for the *promising* languages only.

## RT4 — Multi-turn / agentic porting (tool use)

**Considered:** let the porter iterate, run the port, fix errors.
**Rejected (for now):** one-shot per language keeps the experiment clean,
cheap, and deterministic, and the repo a faithful log. Agentic refinement is a
likely Phase 2 for the top-ranked languages.

## RT5 — Parallel ports

**Considered:** fan out all 138 languages at once.
**Rejected:** "one language at a time" per the task; also keeps token spend
predictable and the git log readable.

## RT6 — Line-count as the reduction metric

**Considered:** measure reduction in lines of code.
**Rejected:** lines vary wildly by formatting/style. Token count
(`cl100k_base`) is a more stable measure of "how much information/content" and
is comparable across languages on one yardstick. We record both.

## RT7 — Let the judge score compile/runnability

**Considered:** have the judge attempt to reason about whether the port
compiles.
**Rejected:** a judge cannot reliably determine compilability by reading code,
especially for 138 languages it may not know well. We restrict the judge to
completeness, which it can assess from the API/SQL/architecture checklist.

## RT8 — Use the real sqlite.org source tree (non-amalgamation)

**Considered:** clone the full SQLite source repo and port selected modules
(`parse.y`, `vdbe.c`, `btree.c`, etc.).
**Rejected:** each module is large and tightly coupled to SQLite internals;
assembling a bounded-but-faithful slice is a research project of its own. Our
hand-written `sqlite_core.c` captures the same *architecture* in a
LLM-portable size, which is what the experiment needs.
