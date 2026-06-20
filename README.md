# essence

A data-driven attempt to **shrink existing projects 10–100x by porting them to
various languages**, then measuring and judging the results.

We crawl the language list from [learnxinyminutes.com](https://learnxinyminutes.com/),
port a bounded target project to each language **one at a time** with an LLM
porter (GLM-5.2 on Fireworks via the exe.dev gateway), count tokens, and have a
separate judge agent (Claude Haiku 4.5) score each port's completeness. The
target project is a compact SQLite-style SQL engine (`source/sqlite_core.c`).

See **[LANGUAGES.md](LANGUAGES.md)** for the live leaderboard.

## Docs

- [Goals](docs/GOALS.md)
- [How it works](docs/HOW_IT_WORKS.md)
- [Decisions](docs/DECISIONS.md)
- [Findings](docs/findings.md)
- [Roads not taken](docs/roads-not-taken.md)

## Quick start

```sh
python3 tools/crawl_lxim.py --out languages.json   # refresh the language list
python3 tools/loop.py --only python                 # port one language
python3 tools/loop.py --limit 10                    # port the top 10 by promise
python3 tools/loop.py                               # port everything
```

## Status

Early. The loop runs end-to-end and produces real, runnable ports (the Python
port reproduces the C reference's demo output). Next: run across the language
set, then promote to a cron job.
