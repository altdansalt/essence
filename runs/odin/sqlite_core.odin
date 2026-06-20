package main

import "core:fmt"
import "core:strings"

// ---------- Value ----------
VType :: enum { NULL, INT, TEXT }

Value :: struct {
	type: VType,
	ival: i64,
	sval: string,
}

v_null :: proc() -> Value { return Value{type = .NULL} }
v_int  :: proc(i: i64) -> Value { return Value{type = .INT, ival = i} }
v_text :: proc(s: string) -> Value { return Value{type = .TEXT, sval = s} }

v_copy :: proc(v: Value) -> Value {
	if v.type == .TEXT { return v_text(v.sval) }
	return v
}

v_cmp :: proc(a, b: Value) -> int {
	if a.type != b.type { return int(a.type) - int(b.type) }
	switch a.type {
	case .INT:
		if a.ival < b.ival { return -1 }
		if a.ival > b.ival { return 1 }
		return 0
	case .TEXT:
		return strings.compare(a.sval, b.sval)
	case: return 0
	}
}

v_to_text :: proc(v: Value) -> string {
	switch v.type {
	case .INT:  return fmt.tprintf("%d", v.ival)
	case .TEXT: return v.sval
	case:       return "NULL"
	}
}

v_truthy :: proc(v: Value) -> bool { return v_cmp(v, v_int(0)) != 0 }

// ---------- Schema ----------
Table :: struct {
	name: string,
	cols: [dynamic]string,
}

Schema :: struct {
	tables: [dynamic]Table,
}

schema_find :: proc(s: ^Schema, name: string) -> ^Table {
	for &t in s.tables {
		if strings.equal_fold(t.name, name) do return &t
	}
	return nil
}

schema_index :: proc(s: ^Schema, name: string) -> int {
	for i, t in s.tables {
		if strings.equal_fold(t.name, name) do return i
	}
	return -1
}

schema_add :: proc(s: ^Schema, name: string, cols: [dynamic]string) -> (int, bool) {
	if schema_find(s, name) != nil { return -1, false }
	append(&s.tables, Table{name = name, cols = cols})
	return len(s.tables) - 1, true
}

table_colindex :: proc(t: ^Table, col: string) -> int {
	for i, c in t.cols {
		if strings.equal_fold(c, col) do return i
	}
	return -1
}

// ---------- Row / store ----------
Row :: struct {
	vals: [dynamic]Value,
}

RowNode :: struct {
	row: Row,
	next: ^RowNode,
}

RowStore :: struct {
	head: ^RowNode,
	tail: ^RowNode,
	nrows: int,
}

// ---------- Lexer ----------
TokKind :: enum {
	EOF, ID, INT, STRING, KW, PUNCT,
	STAR, COMMA, LP, RP, SEMI, OP, DOT,
}

Token :: struct {
	kind: TokKind,
	text: string,
}

KEYWORDS := []string{
	"create", "table", "insert", "into", "values", "select", "from", "where",
	"order", "by", "asc", "desc", "and", "or", "not", "null", "begin", "commit",
	"inner", "join", "on", "int", "integer", "text", "primary", "key", "transaction",
}

is_kw :: proc(s: string) -> bool {
	for k in KEYWORDS {
		if strings.equal_fold(k, s) do return true
	}
	return false
}

Lexer :: struct {
	src: string,
	pos: int,
	toks: [dynamic]Token,
}

lex_push :: proc(L: ^Lexer, k: TokKind, s: string) {
	append(&L.toks, Token{kind = k, text = s})
}

is_alpha :: proc(c: u8) -> bool { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' }
is_alnum :: proc(c: u8) -> bool { return is_alpha(c) || (c >= '0' && c <= '9') }
is_digit :: proc(c: u8) -> bool { return c >= '0' && c <= '9' }
is_space :: proc(c: u8) -> bool { return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == 0x0b || c == 0x0c }

lex :: proc(L: ^Lexer, sql: string) {
	L.src = sql
	L.pos = 0
	clear(&L.toks)

	for L.pos < len(L.src) {
		c := L.src[L.pos]
		if is_space(c) { L.pos += 1; continue }
		if c == '-' && L.pos + 1 < len(L.src) && L.src[L.pos + 1] == '-' {
			for L.pos < len(L.src) && L.src[L.pos] != '\n' { L.pos += 1 }
			continue
		}
		if is_alpha(c) {
			st := L.pos
			for L.pos < len(L.src) && is_alnum(L.src[L.pos]) { L.pos += 1 }
			word := L.src[st:L.pos]
			lex_push(L, is_kw(word) ? .KW : .ID, word)
			continue
		}
		if is_digit(c) {
			st := L.pos
			for L.pos < len(L.src) && is_digit(L.src[L.pos]) { L.pos += 1 }
			lex_push(L, .INT, L.src[st:L.pos])
			continue
		}
		if c == '\'' {
			L.pos += 1
			st := L.pos
			for L.pos < len(L.src) && L.src[L.pos] != '\'' { L.pos += 1 }
			lex_push(L, .STRING, L.src[st:L.pos])
			if L.pos < len(L.src) { L.pos += 1 }
			continue
		}
		if c == '"' {
			L.pos += 1
			st := L.pos
			for L.pos < len(L.src) && L.src[L.pos] != '"' { L.pos += 1 }
			lex_push(L, .ID, L.src[st:L.pos])
			if L.pos < len(L.src) { L.pos += 1 }
			continue
		}
		switch c {
		case '*': lex_push(L, .STAR, "*"); L.pos += 1
		case ',': lex_push(L, .COMMA, ","); L.pos += 1
		case '(': lex_push(L, .LP, "("); L.pos += 1
		case ')': lex_push(L, .RP, ")"); L.pos += 1
		case ';': lex_push(L, .SEMI, ";"); L.pos += 1
		case '.': lex_push(L, .DOT, "."); L.pos += 1
		case:
			if c == '=' || c == '<' || c == '>' || c == '!' {
				st := L.pos
				if L.pos + 1 < len(L.src) && L.src[L.pos + 1] == '=' { L.pos += 1 }
				if c == '<' && L.pos + 1 < len(L.src) && L.src[L.pos + 1] == '>' { L.pos += 1 }
				if c == '!' && L.pos + 1 < len(L.src) && L.src[L.pos + 1] == '=' { L.pos += 1 }
				L.pos += 1
				lex_push(L, .OP, L.src[st:L.pos])
			} else {
				lex_push(L, .PUNCT, string([?]u8{c}))
				L.pos += 1
			}
		}
	}
	lex_push(L, .EOF, "")
}

// ---------- AST ----------
ExprKind :: enum { COL, INT_LIT, STR_LIT, BINOP }

Expr :: struct {
	kind: ExprKind,
	col: string,
	ival: i64,
	sval: string,
	op: string,
	l: ^Expr,
	r: ^Expr,
}

ResultCol :: struct {
	col: string,
	star: bool,
}

TableRef :: struct {
	tname: string,
	alias: string,
}

Stmt :: struct {
	is_create: bool,
	is_insert: bool,
	is_select: bool,
	is_begin: bool,
	is_commit: bool,

	ct_name: string,
	ct_cols: [dynamic]string,

	ins_table: string,
	ins_vals: [dynamic]Value,

	sel_cols: [dynamic]ResultCol,
	sel_star: bool,
	sel_tables: [dynamic]TableRef,
	sel_where: ^Expr,
	sel_order_col: string,
	sel_order_desc: bool,
	sel_join_on: ^Expr,
}

new_expr :: proc(k: ExprKind) -> ^Expr {
	e := new(Expr)
	e.kind = k
	return e
}

free_expr :: proc(e: ^Expr) {
	if e == nil { return }
	free_expr(e.l)
	free_expr(e.r)
	free(e)
}

// ---------- Parser ----------
Parser :: struct {
	t: []Token,
	i: int,
}

p_accept :: proc(P: ^Parser, k: TokKind, text: string) -> bool {
	if P.t[P.i].kind != k { return false }
	if len(text) > 0 && !strings.equal_fold(P.t[P.i].text, text) { return false }
	P.i += 1
	return true
}

p_accept_kw :: proc(P: ^Parser, kw: string) -> bool { return p_accept(P, .KW, kw) }

p_peek_kw :: proc(P: ^Parser, kw: string) -> bool {
	return P.t[P.i].kind == .KW && strings.equal_fold(P.t[P.i].text, kw)
}

parse_primary :: proc(P: ^Parser) -> ^Expr {
	t := &P.t[P.i]
	if t.kind == .INT {
		e := new_expr(.INT_LIT)
		e.ival = parse_int(t.text)
		P.i += 1
		return e
	}
	if t.kind == .STRING {
		e := new_expr(.STR_LIT)
		e.sval = t.text
		P.i += 1
		return e
	}
	if t.kind == .ID || t.kind == .KW {
		e := new_expr(.COL)
		buf := t.text
		P.i += 1
		if P.t[P.i].kind == .DOT {
			P.i += 1
			buf = fmt.tprintf("%s.%s", buf, P.t[P.i].text)
			P.i += 1
		}
		e.col = buf
		return e
	}
	if p_accept(P, .LP, "") {
		e := parse_expr(P)
		p_accept(P, .RP, "")
		return e
	}
	return nil
}

parse_cmp :: proc(P: ^Parser) -> ^Expr {
	l := parse_primary(P)
	if P.t[P.i].kind == .OP {
		e := new_expr(.BINOP)
		e.op = P.t[P.i].text
		P.i += 1
		e.l = l
		e.r = parse_primary(P)
		return e
	}
	return l
}

parse_expr :: proc(P: ^Parser) -> ^Expr {
	l := parse_cmp(P)
	if p_peek_kw(P, "and") || p_peek_kw(P, "or") {
		e := new_expr(.BINOP)
		e.op = p_peek_kw(P, "and") ? "AND" : "OR"
		P.i += 1
		e.l = l
		e.r = parse_expr(P)
		return e
	}
	return l
}

parse_create :: proc(P: ^Parser, st: ^Stmt) -> bool {
	st.is_create = true
	if P.t[P.i].kind != .ID && P.t[P.i].kind != .KW { return false }
	st.ct_name = P.t[P.i].text
	P.i += 1
	if !p_accept(P, .LP, "") { return false }
	for P.t[P.i].kind != .RP && P.t[P.i].kind != .EOF {
		if P.t[P.i].kind != .ID && P.t[P.i].kind != .KW { return false }
		append(&st.ct_cols, P.t[P.i].text)
		P.i += 1
		for P.t[P.i].kind != .COMMA && P.t[P.i].kind != .RP && P.t[P.i].kind != .EOF { P.i += 1 }
		p_accept(P, .COMMA, "")
	}
	p_accept(P, .RP, "")
	return true
}

parse_insert :: proc(P: ^Parser, st: ^Stmt) -> bool {
	st.is_insert = true
	if !p_accept_kw(P, "into") { return false }
	if P.t[P.i].kind != .ID { return false }
	st.ins_table = P.t[P.i].text
	P.i += 1
	if !p_accept_kw(P, "values") { return false }
	if !p_accept(P, .LP, "") { return false }
	for P.t[P.i].kind != .RP && P.t[P.i].kind != .EOF {
		if P.t[P.i].kind == .INT {
			append(&st.ins_vals, v_int(parse_int(P.t[P.i].text)))
		} else if P.t[P.i].kind == .STRING {
			append(&st.ins_vals, v_text(P.t[P.i].text))
		} else if p_accept_kw(P, "null") {
			append(&st.ins_vals, v_null())
		} else {
			return false
		}
		if P.t[P.i].kind != .RP && P.t[P.i].kind != .EOF { P.i += 1 }
		if !p_accept(P, .COMMA, "") { break }
	}
	if !p_accept(P, .RP, "") { return false }
	return true
}

parse_select :: proc(P: ^Parser, st: ^Stmt) -> bool {
	st.is_select = true
	if p_accept(P, .STAR, "") {
		st.sel_star = true
	} else {
		do {
			rc := ResultCol{star = false}
			if p_accept(P, .STAR, "") {
				rc.star = true
			} else if P.t[P.i].kind == .ID || P.t[P.i].kind == .KW {
				buf := P.t[P.i].text
				P.i += 1
				if P.t[P.i].kind == .DOT {
					P.i += 1
					if p_accept(P, .STAR, "") {
						rc.star = true
					} else {
						buf = fmt.tprintf("%s.%s", buf, P.t[P.i].text)
						P.i += 1
						rc.col = buf
					}
				} else {
					rc.col = buf
				}
			} else {
				return false
			}
			append(&st.sel_cols, rc)
		} while p_accept(P, .COMMA, "")
	}
	if !p_accept_kw(P, "from") { return false }
	if P.t[P.i].kind != .ID { return false }

	// first table
	tr := TableRef{tname = P.t[P.i].text}
	P.i += 1
	if P.t[P.i].kind == .ID && !p_peek_kw(P, "on") && !p_peek_kw(P, "where") &&
	   !p_peek_kw(P, "order") && !p_peek_kw(P, "inner") && !p_peek_kw(P, "join") {
		tr.alias = P.t[P.i].text
		P.i += 1
	}
	append(&st.sel_tables, tr)

	// joins
	for p_peek_kw(P, "inner") || p_peek_kw(P, "join") {
		if p_accept_kw(P, "inner") {
			if !p_accept_kw(P, "join") { return false }
		} else {
			p_accept_kw(P, "join")
		}
		if P.t[P.i].kind != .ID { return false }
		tr2 := TableRef{tname = P.t[P.i].text}
		P.i += 1
		if P.t[P.i].kind == .ID && !p_peek_kw(P, "on") && !p_peek_kw(P, "where") && !p_peek_kw(P, "order") {
			tr2.alias = P.t[P.i].text
			P.i += 1
		}
		append(&st.sel_tables, tr2)
		if p_accept_kw(P, "on") {
			on := parse_expr(P)
			if st.sel_join_on == nil {
				st.sel_join_on = on
			} else {
				and_e := new_expr(.BINOP)
				and_e.op = "AND"
				and_e.l = st.sel_join_on
				and_e.r = on
				st.sel_join_on = and_e
			}
		}
	}

	if p_accept_kw(P, "where") { st.sel_where = parse_expr(P) }
	if p_accept_kw(P, "order") {
		if !p_accept_kw(P, "by") { return false }
		if P.t[P.i].kind != .ID && P.t[P.i].kind != .KW { return false }
		st.sel_order_col = P.t[P.i].text
		P.i += 1
		if p_accept_kw(P, "desc") { st.sel_order_desc = true }
		else { p_accept_kw(P, "asc") }
	}
	return true
}

parse :: proc(P: ^Parser, st: ^Stmt) -> bool {
	if p_peek_kw(P, "begin") {
		st.is_begin = true
		P.i += 1
		p_accept_kw(P, "transaction")
	} else if p_peek_kw(P, "commit") {
		st.is_commit = true
		P.i += 1
		p_accept_kw(P, "transaction")
	} else if p_accept_kw(P, "create") {
		if p_accept_kw(P, "table") {
			if !parse_create(P, st) { return false }
		} else { return false }
	} else if p_accept_kw(P, "insert") {
		if !parse_insert(P, st) { return false }
	} else if p_accept_kw(P, "select") {
		if !parse_select(P, st) { return false }
	} else {
		return false
	}
	p_accept(P, .SEMI, "")
	return true
}

free_stmt :: proc(st: ^Stmt) {
	free_expr(st.sel_where)
	free_expr(st.sel_join_on)
}

// ---------- Database ----------
DB :: struct {
	schema: Schema,
	stores: [dynamic]RowStore,
	errmsg: string,
	in_txn: bool,
}

db_exec_create :: proc(db: ^DB, st: ^Stmt) -> int {
	cols := st.ct_cols
	_, ok := schema_add(&db.schema, st.ct_name, cols)
	if !ok {
		db.errmsg = fmt.tprintf("table already exists: %s", st.ct_name)
		return -1
	}
	st.ct_cols = {}
	append(&db.stores, RowStore{})
	return 0
}

db_exec_insert :: proc(db: ^DB, st: ^Stmt) -> int {
	idx := schema_index(&db.schema, st.ins_table)
	if idx < 0 {
		db.errmsg = fmt.tprintf("no such table: %s", st.ins_table)
		return -1
	}
	rs := &db.stores[idx]
	n := new(RowNode)
	for v in st.ins_vals {
		append(&n.row.vals, v_copy(v))
	}
	if rs.tail != nil {
		rs.tail.next = n
	} else {
		rs.head = n
	}
	rs.tail = n
	rs.nrows += 1
	return 0
}

// ---------- expression eval ----------
RowCtx :: struct {
	refs: []TableRef,
	tabs: []^Table,
	rows: []Row,
}

rowctx_colindex :: proc(c: ^RowCtx, col: string) -> (int, int, bool) {
	dot := strings.index(col, ".")
	if dot >= 0 {
		tname := col[:dot]
		cname := col[dot+1:]
		for i in 0..<len(c.refs) {
			tn := c.refs[i].alias
			if len(tn) == 0 { tn = c.refs[i].tname }
			if strings.equal_fold(tn, tname) {
				ci := table_colindex(c.tabs[i], cname)
				if ci >= 0 { return i, ci, true }
			}
		}
		return 0, 0, false
	}
	for i in 0..<len(c.tabs) {
		ci := table_colindex(c.tabs[i], col)
		if ci >= 0 { return i, ci, true }
	}
	return 0, 0, false
}

eval_expr :: proc(e: ^Expr, c: ^RowCtx) -> Value {
	if e == nil { return v_null() }
	switch e.kind {
	case .INT_LIT: return v_int(e.ival)
	case .STR_LIT: return v_text(e.sval)
	case .COL:
		ti, ci, ok := rowctx_colindex(c, e.col)
		if !ok { return v_null() }
		return v_copy(c.rows[ti].vals[ci])
	case .BINOP:
		a := eval_expr(e.l, c)
		b := eval_expr(e.r, c)
		res := v_null()
		if strings.equal_fold(e.op, "AND") {
			res = v_int(v_truthy(a) && v_truthy(b) ? 1 : 0)
		} else if strings.equal_fold(e.op, "OR") {
			res = v_int(v_truthy(a) || v_truthy(b) ? 1 : 0)
		} else {
			cmp := v_cmp(a, b)
			switch e.op {
			case "=":  res = v_int(cmp == 0 ? 1 : 0)
			case "<>": res = v_int(cmp != 0 ? 1 : 0)
			case "<":  res = v_int(cmp < 0 ? 1 : 0)
			case ">":  res = v_int(cmp > 0 ? 1 : 0)
			case "<=": res = v_int(cmp <= 0 ? 1 : 0)
			case ">=": res = v_int(cmp >= 0 ? 1 : 0)
			case: res = v_null()
			}
		}
		return res
	case: return v_null()
	}
}

row_match :: proc(where: ^Expr, c: ^RowCtx) -> bool {
	if where == nil { return true }
	v := eval_expr(where, c)
	return v_truthy(v)
}

// ---------- prepared statement ----------
Stmt_Handle :: struct {
	db: ^DB,
	st: Stmt,
	started: bool,
	done: bool,
	outrow: [dynamic]Value,
	sorted: [dynamic]Row,
	cur_sorted: int,
}

collect_matching :: proc(s: ^Stmt_Handle) {
	n := len(s.st.sel_tables)
	idx := make([dynamic]int, n)
	tabs := make([dynamic]^Table, n)
	for i in 0..<n {
		idx[i] = schema_index(&s.db.schema, s.st.sel_tables[i].tname)
		tabs[i] = &s.db.schema.tables[idx[i]]
	}

	cur := make([dynamic]^RowNode, n)
	for i in 0..<n {
		cur[i] = idx[i] >= 0 ? s.db.stores[idx[i]].head : nil
	}

	for {
		ok := true
		for i in 0..<n {
			if cur[i] == nil { ok = false; break }
		}
		if !ok { break }

		rows := make([]Row, n)
		for i in 0..<n { rows[i] = cur[i].row }

		c := RowCtx{refs = s.st.sel_tables[:], tabs = tabs[:], rows = rows}
		if row_match(s.st.sel_where, &c) && (s.st.sel_join_on == nil || row_match(s.st.sel_join_on, &c)) {
			r := Row{}
			for i in 0..<n {
				for j in 0..<len(rows[i].vals) {
					append(&r.vals, v_copy(rows[i].vals[j]))
				}
			}
			append(&s.sorted, r)
		}

		delete(rows)

		// advance innermost
		k := n - 1
		for ; k >= 0; k -= 1 {
			cur[k] = cur[k].next
			if cur[k] != nil { break }
			if k > 0 { cur[k] = idx[k] >= 0 ? s.db.stores[idx[k]].head : nil }
		}
		if k < 0 { break }
	}

	delete(cur)
	delete(idx)
	delete(tabs)

	// ORDER BY
	if len(s.st.sel_order_col) > 0 && len(s.st.sel_tables) == 1 {
		t0 := schema_find(&s.db.schema, s.st.sel_tables[0].tname)
		if t0 != nil {
			cidx := table_colindex(t0, s.st.sel_order_col)
			if cidx >= 0 {
				for i in 1..<len(s.sorted) {
					for j in i; j > 0; j -= 1 {
						a := s.sorted[j-1].vals[cidx]
						b := s.sorted[j].vals[cidx]
						cmp := v_cmp(a, b)
						should_swap := false
						if s.st.sel_order_desc && cmp < 0 { should_swap = true }
						if !s.st.sel_order_desc && cmp > 0 { should_swap = true }
						if should_swap {
							tmp := s.sorted[j-1]
							s.sorted[j-1] = s.sorted[j]
							s.sorted[j] = tmp
						} else {
							break
						}
					}
				}
			}
		}
	}
}

stmt_step_select :: proc(s: ^Stmt_Handle) -> int {
	if !s.started {
		s.started = true
		collect_matching(s)
	}
	if s.cur_sorted >= len(s.sorted) { return 101 } // DONE

	r := &s.sorted[s.cur_sorted]
	s.cur_sorted += 1
	n := len(s.st.sel_tables)
	tabs := make([dynamic]^Table, n)
	for i in 0..<n { tabs[i] = schema_find(&s.db.schema, s.st.sel_tables[i].tname) }

	offsets := make([dynamic]int, n)
	off := 0
	for i in 0..<n { offsets[i] = off; off += len(tabs[i].cols) }

	clear(&s.outrow)
	if s.st.sel_star {
		for i in 0..<n {
			for j in 0..<len(tabs[i].cols) {
				append(&s.outrow, v_copy(r.vals[offsets[i] + j]))
			}
		}
	} else {
		for k in 0..<len(s.st.sel_cols) {
			rc := &s.st.sel_cols[k]
			if rc.star {
				for i in 0..<n {
					for j in 0..<len(tabs[i].cols) {
						append(&s.outrow, v_copy(r.vals[offsets[i] + j]))
					}
				}
			} else {
				dot := strings.index(rc.col, ".")
				ti := 0
				ci := -1
				if dot >= 0 {
					tname := rc.col[:dot]
					cname := rc.col[dot+1:]
					for i in 0..<n {
						tn := s.st.sel_tables[i].alias
						if len(tn) == 0 { tn = s.st.sel_tables[i].tname }
						if strings.equal_fold(tn, tname) {
							ci = table_colindex(tabs[i], cname)
							ti = i
							break
						}
					}
				} else {
					for i in 0..<n {
						ci = table_colindex(tabs[i], rc.col)
						if ci >= 0 { ti = i; break }
					}
				}
				if ci < 0 {
					append(&s.outrow, v_null())
				} else {
					append(&s.outrow, v_copy(r.vals[offsets[ti] + ci]))
				}
			}
		}
	}

	delete(tabs)
	delete(offsets)
	return 100 // ROW
}

// ---------- public API ----------
sqlite3_open :: proc(name: string) -> ^DB {
	_ = name
	db := new(DB)
	return db
}

sqlite3_close :: proc(db: ^DB) -> int {
	if db == nil { return 0 }
	for i in 0..<len(db.schema.tables) {
		no := db.stores[i].head
		for no != nil {
			nx := no.next
			delete(no.row.vals)
			free(no)
			no = nx
		}
		delete(db.schema.tables[i].cols)
	}
	delete(db.schema.tables)
	delete(db.stores)
	free(db)
	return 0
}

sqlite3_errmsg :: proc(db: ^DB) -> string {
	if db == nil { return "" }
	return db.errmsg
}

Exec_Callback :: proc(arg: rawptr, n: int, vals: []string, cols: []string)

sqlite3_exec :: proc(db: ^DB, sql: string, cb: Exec_Callback, arg: rawptr, err: ^string) -> int {
	L := Lexer{}
	lex(&L, sql)
	defer { delete(L.toks) }

	P := Parser{t = L.toks[:], i = 0}
	rc := 0

	for P.t[P.i].kind != .EOF {
		st := Stmt{}
		if !parse(&P, &st) {
			if err != nil { err^ = "parse error" }
			rc = 1
			break
		}
		if st.is_begin {
			db.in_txn = true
		} else if st.is_commit {
			db.in_txn = false
		} else if st.is_create {
			rc = db_exec_create(db, &st)
		} else if st.is_insert {
			rc = db_exec_insert(db, &st)
		} else if st.is_select {
			s := new(Stmt_Handle)
			s.db = db
			s.st = st
			for {
				r := stmt_step_select(s)
				if r != 100 { break }
				vals := make([dynamic]string, s.outrow.len)
				for i in 0..<len(s.outrow) {
					append(&vals, v_to_text(s.outrow[i]))
				}
				if cb != nil { cb(arg, len(s.outrow), vals[:], nil) }
				delete(vals)
			}
			for i in 0..<len(s.sorted) {
				delete(s.sorted[i].vals)
			}
			delete(s.sorted)
			delete(s.outrow)
			free_stmt(&s.st)
			free(s)
		}
		free_stmt(&st)
	}
	if rc != 0 && err != nil && len(err^) == 0 {
		err^ = db.errmsg
	}
	return rc
}

sqlite3_prepare_v2 :: proc(db: ^DB, sql: string, n: int) -> (^Stmt_Handle, int) {
	buf := sql
	if n >= 0 && n < len(sql) { buf = sql[:n] }
	L := Lexer{}
	lex(&L, buf)
	defer { delete(L.toks) }

	P := Parser{t = L.toks[:], i = 0}
	st := Stmt{}
	if !parse(&P, &st) { return nil, 1 }
	s := new(Stmt_Handle)
	s.db = db
	s.st = st
	return s, 0
}

sqlite3_step :: proc(s: ^Stmt_Handle) -> int {
	if s.st.is_select { return stmt_step_select(s) }
	return 101
}

sqlite3_column_count :: proc(s: ^Stmt_Handle) -> int {
	return len(s.outrow)
}

sqlite3_column_text :: proc(s: ^Stmt_Handle, i: int) -> string {
	if i < 0 || i >= len(s.outrow) { return "" }
	return v_to_text(s.outrow[i])
}

sqlite3_column_int64 :: proc(s: ^Stmt_Handle, i: int) -> i64 {
	if i < 0 || i >= len(s.outrow) { return 0 }
	if s.outrow[i].type == .INT { return s.outrow[i].ival }
	return 0
}

sqlite3_finalize :: proc(s: ^Stmt_Handle) -> int {
	if s == nil { return 0 }
	free_stmt(&s.st)
	for i in 0..<len(s.sorted) {
		delete(s.sorted[i].vals)
	}
	delete(s.sorted)
	delete(s.outrow)
	free(s)
	return 0
}

// ---------- demo ----------
print_row :: proc(arg: rawptr, n: int, vals: []string, cols: []string) {
	for i in 0..<n {
		fmt.printf("%s", vals[i])
		if i + 1 < n { fmt.printf(" | ") }
		else { fmt.println() }
	}
}

main :: proc() {
	db := sqlite3_open(":memory:")
	defer sqlite3_close(db)

	err: string = ""
	sql :=
		"CREATE TABLE users (id INTEGER, name TEXT);"
		"INSERT INTO users VALUES (1, 'ada');"
		"INSERT INTO users VALUES (2, 'grace');"
		"INSERT INTO users VALUES (3, 'linus');"
		"SELECT * FROM users WHERE id > 1 ORDER BY id DESC;"

	if sqlite3_exec(db, sql, print_row, nil, &err) != 0 {
		fmt.eprintf("err: %s\n", err)
	}
}
