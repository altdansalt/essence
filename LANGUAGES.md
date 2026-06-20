# Language leaderboard

Sorted by judge completeness, then reduction factor (orig_tokens/port_tokens).
Reduction >1 means the port is smaller than the C reference by token count.

| # | language | completeness | reduction | port/orig tokens | notes |
|---|----------|-------------|-----------|------------------|-------|
| 1 | Python | 42 | 1.69x | 5200/8805 | Python port is incomplete: the Sqlite3Stmt._collect_matching method is truncated |
