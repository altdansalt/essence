# Language leaderboard

Sorted by judge completeness, then reduction factor (orig_tokens/port_tokens).
Reduction >1 means the port is smaller than the C reference by token count.

| # | language | completeness | reduction | port/orig tokens | notes |
|---|----------|-------------|-----------|------------------|-------|
| 1 | Python | 78 | 1.69x | 5200/8805 | Python port covers most API surface (open/exec/prepare/step/finalize/c |
| 2 | Java | 78 | 1.43x | 6175/8805 | Java port captures most C API surface and core SQL features but has st |
| 3 | Rust | 72 | 1.29x | 6805/8805 | The Rust port successfully translates the core architecture (lexer, pa |
| 4 | C# | 72 | 1.27x | 6931/8805 | Port captures most API surface (sqlite3_open/close/exec/prepare_v2/ste |
| 5 | Haxe | 72 | 1.23x | 7182/8805 | Port captures core lexer, parser, and executor structure with correct  |
| 6 | Nostos | 42 | 1.35x | 6506/8805 | The port captures core architectural elements (lexer, parser, AST, sch |
| 7 | F# | 32 | 1.4x | 6298/8805 | The F# port has significant structural issues: Parser class lacks prop |
| 8 | Odin | 15 | n/a | 136/8805 | Port is severely incomplete: only two small cleanup procedures shown ( ⚠️ capped/incomplete |
| 9 | Vim9 script | 8 | n/a | 132/8805 | Port is essentially a stub demo that calls nonexistent Sqlite3 class m ⚠️ capped/incomplete |
