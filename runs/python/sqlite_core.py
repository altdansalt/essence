#!/usr/bin/env python3
"""sqlite_core.py -- a compact, in-memory SQLite-style SQL engine (Python port)."""

import sys
from functools import cmp_to_key
from dataclasses import dataclass, field
from typing import Optional

# ---------- Value ----------
V_NULL, V_INT, V_TEXT = 0, 1, 2

@dataclass
class Value:
    type: int = V_NULL
    ival: int = 0
    sval: str = ""

    @staticmethod
    def null():
        return Value(V_NULL, 0, "")

    @staticmethod
    def integer(i):
        return Value(V_INT, i, "")

    @staticmethod
    def text(s):
        return Value(V_TEXT, 0, s if s is not None else "")

    def copy(self):
        return Value(self.type, self.ival, self.sval)

    def cmp(self, other):
        if self.type != other.type:
            return self.type - other.type
        if self.type == V_INT:
            return -1 if self.ival < other.ival else (1 if self.ival > other.ival else 0)
        if self.type == V_TEXT:
            a, b = self.sval or "", other.sval or ""
            return -1 if a < b else (1 if a > b else 0)
        return 0

    def truthy(self):
        return self.cmp(Value.integer(0)) != 0

    def to_text(self):
        if self.type == V_INT:
            return str(self.ival)
        if self.type == V_TEXT:
            return self.sval
        return "NULL"

# ---------- Schema ----------
@dataclass
class Table:
    name: str
    cols: list

class Schema:
    def __init__(self):
        self.tables = []

    def find(self, name):
        for t in self.tables:
            if t.name.lower() == name.lower():
                return t
        return None

    def index(self, name):
        for i, t in enumerate(self.tables):
            if t.name.lower() == name.lower():
                return i
        return -1

    def add(self, name, cols):
        if self.find(name):
            return -1
        self.tables.append(Table(name, cols))
        return 0

    @staticmethod
    def colindex(table, col):
        for i, c in enumerate(table.cols):
            if c.lower() == col.lower():
                return i
        return -1

# ---------- Row / store ----------
@dataclass
class Row:
    vals: list = field(default_factory=list)

class RowStore:
    def __init__(self):
        self.rows = []

# ---------- Lexer ----------
TK_EOF, TK_ID, TK_INT, TK_STRING, TK_KW, TK_PUNCT = range(6)
TK_STAR, TK_COMMA, TK_LP, TK_RP, TK_SEMI, TK_OP, TK_DOT = range(6, 13)

KEYWORDS = {
    "create","table","insert","into","values","select","from","where",
    "order","by","asc","desc","and","or","not","null","begin","commit",
    "inner","join","on","int","integer","text","primary","key","transaction"
}

@dataclass
class Token:
    kind: int
    text: str

def lex(sql):
    toks = []
    pos, n = 0, len(sql)
    while pos < n:
        c = sql[pos]
        if c.isspace():
            pos += 1; continue
        if c == '-' and pos + 1 < n and sql[pos+1] == '-':
            while pos < n and sql[pos] != '\n': pos += 1
            continue
        if c.isalpha() or c == '_':
            st = pos
            while pos < n and (sql[pos].isalnum() or sql[pos] == '_'): pos += 1
            word = sql[st:pos]
            toks.append(Token(TK_KW if word.lower() in KEYWORDS else TK_ID, word))
            continue
        if c.isdigit():
            st = pos
            while pos < n and sql[pos].isdigit(): pos += 1
            toks.append(Token(TK_INT, sql[st:pos])); continue
        if c == "'":
            pos += 1; st = pos
            while pos < n and sql[pos] != "'": pos += 1
            toks.append(Token(TK_STRING, sql[st:pos]))
            if pos < n: pos += 1
            continue
        if c == '"':
            pos += 1; st = pos
            while pos < n and sql[pos] != '"': pos += 1
            toks.append(Token(TK_ID, sql[st:pos]))
            if pos < n: pos += 1
            continue
        single = {'*':TK_STAR,',':TK_COMMA,'(':TK_LP,')':TK_RP,';':TK_SEMI,'.':TK_DOT}
        if c in single:
            toks.append(Token(single[c], c)); pos += 1; continue
        if c in "=<>!":
            st = pos
            if pos+1<n and sql[pos+1]=='=': pos += 1
            if c=='<' and pos+1<n and sql[pos+1]=='>': pos += 1
            if c=='!' and pos+1<n and sql[pos+1]=='=': pos += 1
            pos += 1
            toks.append(Token(TK_OP, sql[st:pos])); continue
        toks.append(Token(TK_PUNCT, c)); pos += 1
    toks.append(Token(TK_EOF, ""))
    return toks

# ---------- AST ----------
@dataclass
class Expr:
    kind: str
    col: str = ""
    ival: int = 0
    sval: str = ""
    op: str = ""
    l: Optional['Expr'] = None
    r: Optional['Expr'] = None

@dataclass
class ResultCol:
    col: str = ""
    star: bool = False

@dataclass
class TableRef:
    tname: str = ""
    alias: str = ""

@dataclass
class Stmt:
    is_create: bool = False
    is_insert: bool = False
    is_select: bool = False
    is_begin: bool = False
    is_commit: bool = False
    ct_name: str = ""
    ct_cols: list = field(default_factory=list)
    ins_table: str = ""
    ins_vals: list = field(default_factory=list)
    sel_cols: list = field(default_factory=list)
    sel_star: bool = False
    sel_tables: list = field(default_factory=list)
    sel_where: Optional[Expr] = None
    sel_order_col: str = ""
    sel_order_desc: bool = False
    sel_join_on: Optional[Expr] = None

# ---------- Parser ----------
class Parser:
    def __init__(self, toks):
        self.t = toks; self.i = 0

    def cur(self): return self.t[self.i]

    def accept(self, kind, text=None):
        tok = self.t[self.i]
        if tok.kind != kind: return False
        if text is not None and tok.text.lower() != text.lower(): return False
        self.i += 1; return True

    def accept_kw(self, kw): return self.accept(TK_KW, kw)

    def peek_kw(self, kw):
        tok = self.t[self.i]
        return tok.kind == TK_KW and tok.text.lower() == kw.lower()

    def parse_primary(self):
        tok = self.cur()
        if tok.kind == TK_INT:
            self.i += 1; return Expr("int", ival=int(tok.text))
        if tok.kind == TK_STRING:
            self.i += 1; return Expr("str", sval=tok.text)
        if tok.kind in (TK_ID, TK_KW):
            col = tok.text; self.i += 1
            if self.cur().kind == TK_DOT:
                self.i += 1; col += "." + self.cur().text; self.i += 1
            return Expr("col", col=col)
        if self.accept(TK_LP):
            e = self.parse_expr(); self.accept(TK_RP); return e
        return None

    def parse_cmp(self):
        l = self.parse_primary()
        if self.cur().kind == TK_OP:
            op = self.cur().text; self.i += 1
            r = self.parse_primary()
            return Expr("binop", op=op, l=l, r=r)
        return l

    def parse_expr(self):
        l = self.parse_cmp()
        if self.peek_kw("and") or self.peek_kw("or"):
            op = "AND" if self.peek_kw("and") else "OR"
            self.i += 1; r = self.parse_expr()
            return Expr("binop", op=op, l=l, r=r)
        return l

    def parse_create(self):
        st = Stmt(is_create=True)
        tok = self.cur()
        if tok.kind not in (TK_ID, TK_KW): return None
        st.ct_name = tok.text; self.i += 1
        if not self.accept(TK_LP): return None
        while self.cur().kind not in (TK_RP, TK_EOF):
            tok = self.cur()
            if tok.kind not in (TK_ID, TK_KW): return None
            st.ct_cols.append(tok.text); self.i += 1
            while self.cur().kind not in (TK_COMMA, TK_RP, TK_EOF): self.i += 1
            self.accept(TK_COMMA)
        self.accept(TK_RP)
        return st

    def parse_insert(self):
        st = Stmt(is_insert=True)
        if not self.accept_kw("into"): return None
        if self.cur().kind != TK_ID: return None
        st.ins_table = self.cur().text; self.i += 1
        if not self.accept_kw("values"): return None
        if not self.accept(TK_LP): return None
        while self.cur().kind not in (TK_RP, TK_EOF):
            tok = self.cur()
            if tok.kind == TK_INT:
                st.ins_vals.append(Value.integer(int(tok.text)))
            elif tok.kind == TK_STRING:
                st.ins_vals.append(Value.text(tok.text))
            elif self.accept_kw("null"):
                st.ins_vals.append(Value.null())
            else:
                return None
            self.i += 1
            if not self.accept(TK_COMMA): break
        if not self.accept(TK_RP): return None
        return st

    def parse_select(self):
        st = Stmt(is_select=True)
        if self.accept(TK_STAR):
            st.sel_star = True
        else:
            while True:
                rc = ResultCol()
                if self.accept(TK_STAR):
                    rc.star = True
                elif self.cur().kind in (TK_ID, TK_KW):
                    col = self.cur().text; self.i += 1
                    if self.cur().kind == TK_DOT:
                        self.i += 1
                        if self.accept(TK_STAR):
                            rc.star = True
                        else:
                            col += "." + self.cur().text; self.i += 1; rc.col = col
                    else:
                        rc.col = col
                else:
                    return None
                st.sel_cols.append(rc)
                if not self.accept(TK_COMMA): break
        if not self.accept_kw("from"): return None
        if self.cur().kind != TK_ID: return None
        tr = TableRef(tname=self.cur().text); self.i += 1
        if self.cur().kind == TK_ID and not any(self.peek_kw(k) for k in ("on","where","order","inner","join")):
            tr.alias = self.cur().text; self.i += 1
        st.sel_tables.append(tr)
        while self.peek_kw("inner") or self.peek_kw("join"):
            if self.accept_kw("inner"):
                if not self.accept_kw("join"): return None
            else:
                self.accept_kw("join")
            if self.cur().kind != TK_ID: return None
            tr = TableRef(tname=self.cur().text); self.i += 1
            if self.cur().kind == TK_ID and not any(self.peek_kw(k) for k in ("on","where","order")):
                tr.alias = self.cur().text; self.i += 1
            if self.accept_kw("on"):
                on = self.parse_expr()
                if st.sel_join_on is None:
                    st.sel_join_on = on
                else:
                    st.sel_join_on = Expr("binop", op="AND", l=st.sel_join_on, r=on)
            st.sel_tables.append(tr)
        if self.accept_kw("where"):
            st.sel_where = self.parse_expr()
        if self.accept_kw("order"):
            if not self.accept_kw("by"): return None
            if self.cur().kind not in (TK_ID, TK_KW): return None
            st.sel_order_col = self.cur().text; self.i += 1
            if self.accept_kw("desc"): st.sel_order_desc = True
            else: self.accept_kw("asc")
        return st

    def parse(self):
        if self.peek_kw("begin"):
            st = Stmt(is_begin=True); self.i += 1; self.accept_kw("transaction")
        elif self.peek_kw("commit"):
            st = Stmt(is_commit=True); self.i += 1; self.accept_kw("transaction")
        elif self.accept_kw("create"):
            if self.accept_kw("table"):
                st = self.parse_create()
                if st is None: return None
            else:
                return None
        elif self.accept_kw("insert"):
            st = self.parse_insert()
            if st is None: return None
        elif self.accept_kw("select"):
            st = self.parse_select()
            if st is None: return None
        else:
            return None
        self.accept(TK_SEMI)
        return st

# ---------- Row context & eval ----------
class RowCtx:
    def __init__(self, refs, tabs, rows):
        self.refs = refs; self.tabs = tabs; self.rows = rows

    def colindex(self, col):
        dot = col.find('.')
        if dot >= 0:
            tname, cname = col[:dot], col[dot+1:]
            for i in range(len(self.refs)):
                tn = self.refs[i].alias or self.refs[i].tname
                if tn.lower() == tname.lower():
                    ci = Schema.colindex(self.tabs[i], cname)
                    if ci >= 0: return i, ci
            return -1, -1
        for i in range(len(self.tabs)):
            ci = Schema.colindex(self.tabs[i], col)
            if ci >= 0: return i, ci
        return -1, -1

def eval_expr(e, c):
    if e is None: return Value.null()
    if e.kind == "int": return Value.integer(e.ival)
    if e.kind == "str": return Value.text(e.sval)
    if e.kind == "col":
        ti, ci = c.colindex(e.col)
        if ti < 0: return Value.null()
        return c.rows[ti].vals[ci].copy()
    if e.kind == "binop":
        a, b = eval_expr(e.l, c), eval_expr(e.r, c)
        op = e.op.lower()
        if op == "and": return Value.integer(1 if a.truthy() and b.truthy() else 0)
        if op == "or": return Value.integer(1 if a.truthy() or b.truthy() else 0)
        cmp = a.cmp(b)
        if e.op == "=": return Value.integer(1 if cmp == 0 else 0)
        if e.op == "<>": return Value.integer(1 if cmp != 0 else 0)
        if e.op == "<": return Value.integer(1 if cmp < 0 else 0)
        if e.op == ">": return Value.integer(1 if cmp > 0 else 0)
        if e.op == "<=": return Value.integer(1 if cmp <= 0 else 0)
        if e.op == ">=": return Value.integer(1 if cmp >= 0 else 0)
        return Value.null()
    return Value.null()

def row_match(where, c):
    if where is None: return True
    return eval_expr(where, c).truthy()

# ---------- Database ----------
class Sqlite3:
    def __init__(self):
        self.schema = Schema()
        self.stores = []
        self.errmsg = ""
        self.in_txn = 0

    def _exec_create(self, st):
        if self.schema.add(st.ct_name, st.ct_cols):
            self.errmsg = f"table already exists: {st.ct_name}"
            return 1
        st.ct_cols = []
        self.stores.append(RowStore())
        return 0

    def _exec_insert(self, st):
        idx = self.schema.index(st.ins_table)
        if idx < 0:
            self.errmsg = f"no such table: {st.ins_table}"
            return 1
        self.stores[idx].rows.append(Row(vals=[v.copy() for v in st.ins_vals]))
        return 0

    def open(self, name=":memory:"):
        return self

    def close(self):
        pass

    def errmsg_str(self):
        return self.errmsg

    def exec(self, sql, cb=None, arg=None):
        toks = lex(sql)
        p = Parser(toks)
        rc = 0; err = None
        while p.cur().kind != TK_EOF:
            st = p.parse()
            if st is None:
                err = "parse error"; rc = 1; break
            if st.is_begin: self.in_txn = 1
            elif st.is_commit: self.in_txn = 0
            elif st.is_create: rc = self._exec_create(st)
            elif st.is_insert: rc = self._exec_insert(st)
            elif st.is_select:
                stmt = Sqlite3Stmt(self, st)
                while stmt.step() == 100:
                    vals = [stmt.outrow[i].to_text() for i in range(stmt.nout)]
                    if cb: cb(arg, stmt.nout, vals, None)
                stmt.finalize()
            if rc: break
        if rc and err is None: err = self.errmsg
        if rc and err: self.errmsg = err
        return rc

    def prepare(self, sql, n=-1):
        buf = sql if n < 0 else sql[:n]
        toks = lex(buf)
        p = Parser(toks)
        st = p.parse()
        if st is None: return None
        return Sqlite3Stmt(self, st)

# ---------- Prepared statement ----------
class Sqlite3Stmt:
    def __init__(self, db, st):
        self.db = db; self.st = st
        self.started = False; self.done = False
        self.outrow = []; self.nout = 0
        self.sorted = []; self.cur_sorted = 0

    def _collect_matching(self):
        n = len(self.st.sel_tables)
        idxs = [self.db.schema.index(t.tname) for t in self.st.sel_tables]
        curs = [self.db.stores[idx].rows if idx >= 0 else [] for idx in idxs]
        tabs = [self.db.schema.tables[idx] if idx >= 0 else None for idx in idxs]
        indices = [0] * n
        while True:
            if not all(indices[k] < len(curs[k]) for k in range(n)): break
            rows = [curs[k][indices[k]] for k in range(n)]
            c = RowCtx(self.st.sel_tables, tabs, rows)
            if row_match(self.st.sel_where, c) and (self.st.sel_join_on is None or row_match(self.st.sel_join_on, c)):
                self.sorted.append(Row(vals=[v.copy() for r in rows for v in r.vals]))
            k = n - 1
            while k >= 0:
                indices[k] += 1
                if indices[k] < len(curs[k]): break
                if k > 0: indices[k] = 0
                k -= 1
            if k < 0: break
        if self.st.sel_order_col:
            tabs2 = [self.db.schema.find(t.tname) for t in self.st.sel_tables]
            if len(tabs2) == 1 and tabs2[0] is not None:
                cidx = Schema.colindex(tabs2[0], self.st.sel_order_col)
                if cidx >= 0:
                    desc = self.st.sel_order_desc
                    self.sorted.sort(key=cmp_to_key(lambda ra, rb: ra.vals[cidx].cmp(rb.vals[cidx])), reverse=desc)

    def step(self):
        if not self.st.is_select: return 101
        if not self.started:
            self.started = True; self._collect_matching()
        if self.cur_sorted >= len(self.sorted): return 101
        r = self.sorted[self.cur_sorted]; self.cur_sorted += 1
        n = len(self.st.sel_tables)
        tabs = [self.db.schema.find(t.tname) for t in self.st.sel_tables]
        offsets = []; off = 0
        for i in range(n):
            offsets.append(off); off += len(tabs[i].cols) if tabs[i] else 0
        out = []
        if self.st.sel_star:
            for i in range(n):
                for j in range(len(tabs[i].cols)):
                    out.append(r.vals[offsets[i]+j].copy())
        else:
            for rc in self.st.sel_cols:
                if rc.star:
                    for i in range(n):
                        for j in range(len(tabs[i].cols)):
                            out.append(r.vals[offsets[i]+j].copy())
                else:
                    dot = rc.col.find('.'); ti, ci = 0, -1
                    if dot >= 0:
                        tname, cname = rc.col[:dot], rc.col[dot+1:]
                        for i in range(n):
                            tn = self.st.sel_tables[i].alias or self.st.sel_tables[i].tname
                            if tn.lower() == tname.lower():
                                ci = Schema.colindex(tabs[i], cname); ti = i; break
                    else:
                        for i in range(n):
                            ci = Schema.colindex(tabs[i], rc.col)
                            if ci >= 0: ti = i; break
                    if ci < 0: out.append(Value.null())
                    else: out.append(r.vals[offsets[ti]+ci].copy())
        self.outrow = out; self.nout = len(out)
        return 100

    def column_count(self): return self.nout

    def column_text(self, i):
        if i < 0 or i >= self.nout: return None
        return self.outrow[i].to_text()

    def column_int64(self, i):
        if i < 0 or i >= self.nout: return 0
        return self.outrow[i].ival if self.outrow[i].type == V_INT else 0

    def finalize(self):
        self.sorted = []; self.outrow = []

# ---------- Demo ----------
def print_row(arg, n, vals, cols):
    print(" | ".join(vals))

def main():
    db = Sqlite3()
    db.open(":memory:")
    sql = (
        "CREATE TABLE users (id INTEGER, name TEXT);"
        "INSERT INTO users VALUES (1, 'ada');"
        "INSERT INTO users VALUES (2, 'grace');"
        "INSERT INTO users VALUES (3, 'linus');"
        "SELECT * FROM users WHERE id > 1 ORDER BY id DESC;"
    )
    rc = db.exec(sql, print_row, None)
    if rc:
        print(f"err: {db.errmsg_str()}", file=sys.stderr)
    db.close()

if __name__ == "__main__":
    main()
