# How it works

## Layout

```
tools/
  crawl_lxim.py   # harvest languages from learnxinyminutes
  llm.py          # exe.dev LLM gateway client (porter=GLM-5.2, judge=Haiku 4.5)
  token_count.py  # tiktoken cl100k_base token counting
  loop.py         # the orchestrator
source/
  sqlite_core.c          # the bounded target (a compact SQLite-style engine)
  sqlite_core.test.sql   # the contract: SQL inputs + expected outputs
  README.md
runs/<lang-slug>/
  sqlite_core.<ext>   # the ported source
  meta.json           # tokens, reduction, judge score, usage, timing
  porter_raw.txt      # raw porter response
  judge_raw.txt       # raw judge response
logs/loop.log
languages.json        # crawled language list (with promise_score)
LANGUAGES.md          # leaderboard, rebuilt after each run
docs/                 # this directory
```

## The loop (`tools/loop.py`)

For each language (sorted by `promise_score` desc, then name):

1. **Skip** if `runs/<slug>/meta.json` already exists (idempotent).
2. **Build the porter prompt**: system ("output only a code fence") + user
   (the C source + the language's cheatsheet + the porting requirements).
3. **Call the porter** (GLM-5.2, `reasoning_effort=low`, `max_tokens=16000`).
4. **Extract** the code from the fenced block.
5. **Token-count** the port vs the original.
6. **Call the judge** (Claude Haiku 4.5) with the full port + a completeness
   checklist; parse its JSON score.
7. **Record** `runs/<slug>/` (code, meta, raw responses).
8. **Commit and push** (`port: <slug> ... completeness=N`).
9. On error, write `runs/<slug>/ERROR.txt` and continue.

After all languages: rebuild `LANGUAGES.md` (sorted by completeness, then
reduction) and commit/push.

## Running it

```sh
# one language
python3 tools/loop.py --only python

# the top N by promise
python3 tools/loop.py --limit 10

# all of them (long; ~2–6 min per language)
python3 tools/loop.py

# don't push
python3 tools/loop.py --no-push
```

## Models

- Porter: `accounts/fireworks/models/glm-5p2` (Fireworks, via gateway).
  Override with `PORTER_MODEL=...` and `PORTER_REASONING=low|medium|high`.
- Judge: `claude-haiku-4-5` (Anthropic, via gateway). Override with
  `JUDGE_MODEL=...`.
- Gateway base: `EXEDEV_LLM_GATEWAY` (default
  `http://169.254.169.254/gateway/llm`).
