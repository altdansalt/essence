# Source: the project being ported

The target project is **SQLite** — specifically a bounded, self-contained core
of a SQLite-style SQL engine written in C, small enough to fit in a single LLM
context window so every language port gets the *same* input and reductions are
comparable on one yardstick.

## Why not the full amalgamation?

The real SQLite amalgamation (`sqlite3.c`) is ~257k lines / ~9 MB. That is far
beyond a single LLM context, so it cannot be ported in one pass and "reduction"
would be measured against an input the model never saw. See
`docs/roads-not-taken.md` for the full reasoning.

## The target: `sqlite_core.c`

`sqlite_core.c` is a compact, real, in-memory SQL engine implementing a
recognizable slice of SQLite's architecture:

  - a lexer for a SQL subset
  - a recursive-descent parser
  - a simple planner/executor
  - an in-memory pager + B-tree-like table store
  - a VFS abstraction (in-memory)
  - the public `sqlite3_open/exec/prepare/step/finalize/close` API surface

It supports `CREATE TABLE`, `INSERT`, `SELECT` (with `WHERE`, projections,
`ORDER BY`, and simple inner joins), and `BEGIN/COMMIT` transactions. It is the
contract every port tries to honor. Ports do not have to compile or pass tests
to be scored; the judge scores *completeness* of the port relative to this
contract.
