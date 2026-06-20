# Goals

`essence` is a data-driven attempt to **shrink existing projects 10–100x by
porting them to various languages**, then measuring and judging the results.

## Thesis

Different programming languages let you express the same behavior with
different amounts of code. A 257k-line C program (SQLite) might be a 5k-line
Haskell program, a 12k-line Python program, or a 40k-line Java program. We
want to *measure* that, language by language, with real LLM-generated ports,
and rank languages by how much they shrink a real project while preserving
behavior.

## Concrete goals

1. **Crawl** the set of programming languages from
   [learnxinyminutes.com](https://learnxinyminutes.com/) (`tools/crawl_lxim.py`).
2. **Port** a bounded target project to each language, **one language at a
   time**, using an LLM porter (GLM-5.2 on Fireworks, via the exe.dev LLM
   gateway). The target starts with **SQLite** — specifically the bounded
   `source/sqlite_core.c` core.
3. **Sort** languages by likelihood of useful reduction (a heuristic
   `promise_score` from the cheatsheet, then refined by real results).
4. **Count tokens** (`tools/token_count.py`, tiktoken `cl100k_base`) for the
   original and every port, so reductions are comparable on one yardstick.
5. **Judge** each port with a *separate* agent (Claude Haiku 4.5) that scores
   completeness (API surface, SQL features, architecture) — not whether it
   compiles or runs, which we cannot verify for every language.
6. **Record everything** in this repo: ports (`runs/<lang>/`), findings,
   decisions, roads not taken, goals, and a leaderboard (`LANGUAGES.md`).
7. **Commit and push often** — after every language port.
8. Eventually **turn the loop into a cron job** once it is trusted.

## What "good" looks like

A language that is both **high-completeness** (the port preserves the target's
behavior) and **high-reduction** (the port is much smaller by token count) is a
promising language to explore further. The leaderboard sorts on completeness
first, then reduction factor (`orig_tokens / port_tokens`).

## Non-goals (for now)

- Ports do **not** have to compile or pass tests. We are gathering promising
  languages to explore further, not shipping products.
- We are not yet optimizing the porter's prompt or doing multi-turn refinement.
  One shot per language to start.
