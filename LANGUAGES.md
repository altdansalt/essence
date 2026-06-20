# Language leaderboard

Sorted by judge completeness, then reduction factor (orig_tokens/port_tokens).
Reduction >1 means the port is smaller than the C reference by token count.

| # | language | completeness | reduction | port/orig tokens | notes |
|---|----------|-------------|-----------|------------------|-------|
| 1 | Python | 78 | 1.69x | 5200/8805 | Python port covers most API surface (open/exec/prepare/step/finalize/close/colum |
| 2 | Java | 78 | 1.43x | 6175/8805 | Java port captures most C API surface and core SQL features but has structural g |
| 3 | Rust | 72 | 1.29x | 6805/8805 | The Rust port successfully translates the core architecture (lexer, parser, exec |
| 4 | C# | 72 | 1.27x | 6931/8805 | Port captures most API surface (sqlite3_open/close/exec/prepare_v2/step/finalize |
| 5 | Haxe | 72 | 1.23x | 7182/8805 | Port captures core lexer, parser, and executor structure with correct SQL featur |
| 6 | Odin | 42 | 9.37x | 940/8805 | Port covers core API functions but lacks critical infrastructure: lexer, parser, |
| 7 | Vim9 script | 15 | 9.49x | 928/8805 | Port is severely incomplete: only lexer stub is present with no parser, AST, exe |
| 8 | F# | 2 | 489.17x | 18/8805 | The port submission contains only a single line of C code fragment, not a meanin |
| 9 | Nostos | 2 | 214.76x | 41/8805 | Ported code is a trivial struct mutation example in an unrelated language (Nosto |
