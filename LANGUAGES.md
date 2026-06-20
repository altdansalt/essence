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
