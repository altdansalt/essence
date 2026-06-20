use std::cell::RefCell;
use std::rc::Rc;

// ---------- Value ----------
#[derive(Clone, Debug)]
enum Value {
    Null,
    Int(i64),
    Text(String),
}

impl Value {
    fn cmp(&self, other: &Value) -> std::cmp::Ordering {
        use std::cmp::Ordering;
        match (self, other) {
            (Value::Null, Value::Null) => Ordering::Equal,
            (Value::Null, _) => Ordering::Less,
            (_, Value::Null) => Ordering::Greater,
            (Value::Int(a), Value::Int(b)) => a.cmp(b),
            (Value::Text(a), Value::Text(b)) => a.cmp(b),
            (Value::Int(_), Value::Text(_)) => Ordering::Less,
            (Value::Text(_), Value::Int(_)) => Ordering::Greater,
        }
    }
    fn truthy(&self) -> bool {
        self.cmp(&Value::Int(0)) != std::cmp::Ordering::Equal
    }
    fn to_text(&self) -> String {
        match self {
            Value::Int(i) => i.to_string(),
            Value::Text(s) => s.clone(),
            Value::Null => "NULL".to_string(),
        }
    }
}

// ---------- Schema ----------
struct Table {
    name: String,
    cols: Vec<String>,
}

impl Table {
    fn colindex(&self, col: &str) -> Option<usize> {
        self.cols.iter().position(|c| c.eq_ignore_ascii_case(col))
    }
}

// ---------- Row / store ----------
type Row = Vec<Value>;

struct RowStore {
    rows: Vec<Row>,
}

// ---------- Lexer ----------
#[derive(Clone, Debug, PartialEq)]
enum TokKind {
    Eof,
    Id,
    Int,
    String,
    Kw,
    Punct,
    Star,
    Comma,
    Lp,
    Rp,
    Semi,
    Op,
    Dot,
}

#[derive(Clone, Debug)]
struct Token {
    kind: TokKind,
    text: String,
}

const KEYWORDS: &[&str] = &[
    "create", "table", "insert", "into", "values", "select", "from", "where",
    "order", "by", "asc", "desc", "and", "or", "not", "null", "begin", "commit",
    "inner", "join", "on", "int", "integer", "text", "primary", "key", "transaction",
];

fn is_kw(s: &str) -> bool {
    KEYWORDS.iter().any(|k| k.eq_ignore_ascii_case(s))
}

fn lex(sql: &str) -> Vec<Token> {
    let chars: Vec<char> = sql.chars().collect();
    let mut pos = 0;
    let mut toks = Vec::new();
    while pos < chars.len() {
        let c = chars[pos];
        if c.is_whitespace() {
            pos += 1;
            continue;
        }
        if c == '-' && pos + 1 < chars.len() && chars[pos + 1] == '-' {
            while pos < chars.len() && chars[pos] != '\n' {
                pos += 1;
            }
            continue;
        }
        if c.is_alphabetic() || c == '_' {
            let st = pos;
            while pos < chars.len() && (chars[pos].is_alphanumeric() || chars[pos] == '_') {
                pos += 1;
            }
            let s: String = chars[st..pos].iter().collect();
            toks.push(Token {
                kind: if is_kw(&s) { TokKind::Kw } else { TokKind::Id },
                text: s,
            });
            continue;
        }
        if c.is_ascii_digit() {
            let st = pos;
            while pos < chars.len() && chars[pos].is_ascii_digit() {
                pos += 1;
            }
            toks.push(Token {
                kind: TokKind::Int,
                text: chars[st..pos].iter().collect(),
            });
            continue;
        }
        if c == '\'' {
            pos += 1;
            let st = pos;
            while pos < chars.len() && chars[pos] != '\'' {
                pos += 1;
            }
            toks.push(Token {
                kind: TokKind::String,
                text: chars[st..pos].iter().collect(),
            });
            if pos < chars.len() {
                pos += 1;
            }
            continue;
        }
        if c == '"' {
            pos += 1;
            let st = pos;
            while pos < chars.len() && chars[pos] != '"' {
                pos += 1;
            }
            toks.push(Token {
                kind: TokKind::Id,
                text: chars[st..pos].iter().collect(),
            });
            if pos < chars.len() {
                pos += 1;
            }
            continue;
        }
        match c {
            '*' => { toks.push(Token { kind: TokKind::Star, text: "*".into() }); pos += 1; }
            ',' => { toks.push(Token { kind: TokKind::Comma, text: ",".into() }); pos += 1; }
            '(' => { toks.push(Token { kind: TokKind::Lp, text: "(".into() }); pos += 1; }
            ')' => { toks.push(Token { kind: TokKind::Rp, text: ")".into() }); pos += 1; }
            ';' => { toks.push(Token { kind: TokKind::Semi, text: ";".into() }); pos += 1; }
            '.' => { toks.push(Token { kind: TokKind::Dot, text: ".".into() }); pos += 1; }
            _ if "=<>!".contains(c) => {
                let st = pos;
                if pos + 1 < chars.len() && chars[pos + 1] == '=' {
                    pos += 1;
                }
                if c == '<' && pos + 1 < chars.len() && chars[pos + 1] == '>' {
                    pos += 1;
                }
                if c == '!' && pos + 1 < chars.len() && chars[pos + 1] == '=' {
                    pos += 1;
                }
                pos += 1;
                toks.push(Token {
                    kind: TokKind::Op,
                    text: chars[st..pos].iter().collect(),
                });
            }
            _ => {
                toks.push(Token { kind: TokKind::Punct, text: c.to_string() });
                pos += 1;
            }
        }
    }
    toks.push(Token { kind: TokKind::Eof, text: "".into() });
    toks
}

// ---------- AST ----------
#[derive(Debug)]
enum Expr {
    Col(String),
    Int(i64),
    Str(String),
    BinOp(String, Box<Expr>, Box<Expr>),
}

#[derive(Debug)]
struct ResultCol {
    col: Option<String>,
    star: bool,
}

#[derive(Debug, Clone)]
struct TableRef {
    tname: String,
    alias: Option<String>,
}

#[derive(Debug)]
enum Stmt {
    Create { name: String, cols: Vec<String> },
    Insert { table: String, vals: Vec<Value> },
    Select {
        cols: Vec<ResultCol>,
        star: bool,
        tables: Vec<TableRef>,
        where_: Option<Expr>,
        order_col: Option<String>,
        order_desc: bool,
        join_on: Option<Expr>,
    },
    Begin,
    Commit,
}

// ---------- Parser ----------
struct Parser {
    t: Vec<Token>,
    i: usize,
}

impl Parser {
    fn peek(&self) -> &Token {
        &self.t[self.i]
    }
    fn accept(&mut self, k: TokKind, text: Option<&str>) -> bool {
        if self.t[self.i].kind != k {
            return false;
        }
        if let Some(tx) = text {
            if !self.t[self.i].text.eq_ignore_ascii_case(tx) {
                return false;
            }
        }
        self.i += 1;
        true
    }
    fn accept_kw(&mut self, kw: &str) -> bool {
        self.accept(TokKind::Kw, Some(kw))
    }
    fn peek_kw(&self, kw: &str) -> bool {
        self.t[self.i].kind == TokKind::Kw && self.t[self.i].text.eq_ignore_ascii_case(kw)
    }

    fn parse_primary(&mut self) -> Option<Expr> {
        let t = &self.t[self.i].clone();
        match t.kind {
            TokKind::Int => {
                let v: i64 = t.text.parse().unwrap_or(0);
                self.i += 1;
                Some(Expr::Int(v))
            }
            TokKind::String => {
                let s = t.text.clone();
                self.i += 1;
                Some(Expr::Str(s))
            }
            TokKind::Id | TokKind::Kw => {
                let mut buf = t.text.clone();
                self.i += 1;
                if self.t[self.i].kind == TokKind::Dot {
                    self.i += 1;
                    buf.push('.');
                    buf.push_str(&self.t[self.i].text);
                    self.i += 1;
                }
                Some(Expr::Col(buf))
            }
            TokKind::Lp => {
                self.i += 1;
                let e = self.parse_expr();
                self.accept(TokKind::Rp, None);
                e
            }
            _ => None,
        }
    }

    fn parse_cmp(&mut self) -> Option<Expr> {
        let l = self.parse_primary()?;
        if self.t[self.i].kind == TokKind::Op {
            let op = self.t[self.i].text.clone();
            self.i += 1;
            let r = self.parse_primary()?;
            Some(Expr::BinOp(op, Box::new(l), Box::new(r)))
        } else {
            Some(l)
        }
    }

    fn parse_expr(&mut self) -> Option<Expr> {
        let l = self.parse_cmp()?;
        if self.peek_kw("and") || self.peek_kw("or") {
            let op = if self.peek_kw("and") { "AND" } else { "OR" };
            self.i += 1;
            let r = self.parse_expr()?;
            Some(Expr::BinOp(op.to_string(), Box::new(l), Box::new(r)))
        } else {
            Some(l)
        }
    }

    fn parse_create(&mut self) -> Option<Stmt> {
        let t = self.t[self.i].clone();
        if t.kind != TokKind::Id && t.kind != TokKind::Kw {
            return None;
        }
        let name = t.text;
        self.i += 1;
        if !self.accept(TokKind::Lp, None) {
            return None;
        }
        let mut cols = Vec::new();
        while self.t[self.i].kind != TokKind::Rp && self.t[self.i].kind != TokKind::Eof {
            let t2 = self.t[self.i].clone();
            if t2.kind != TokKind::Id && t2.kind != TokKind::Kw {
                return None;
            }
            cols.push(t2.text);
            self.i += 1;
            while self.t[self.i].kind != TokKind::Comma
                && self.t[self.i].kind != TokKind::Rp
                && self.t[self.i].kind != TokKind::Eof
            {
                self.i += 1;
            }
            self.accept(TokKind::Comma, None);
        }
        self.accept(TokKind::Rp, None);
        Some(Stmt::Create { name, cols })
    }

    fn parse_insert(&mut self) -> Option<Stmt> {
        if !self.accept_kw("into") {
            return None;
        }
        if self.t[self.i].kind != TokKind::Id {
            return None;
        }
        let table = self.t[self.i].text.clone();
        self.i += 1;
        if !self.accept_kw("values") {
            return None;
        }
        if !self.accept(TokKind::Lp, None) {
            return None;
        }
        let mut vals = Vec::new();
        while self.t[self.i].kind != TokKind::Rp && self.t[self.i].kind != TokKind::Eof {
            let t = self.t[self.i].clone();
            if t.kind == TokKind::Int {
                vals.push(Value::Int(t.text.parse().unwrap_or(0)));
                self.i += 1;
            } else if t.kind == TokKind::String {
                vals.push(Value::Text(t.text));
                self.i += 1;
            } else if self.accept_kw("null") {
                vals.push(Value::Null);
            } else {
                return None;
            }
            if !self.accept(TokKind::Comma, None) {
                break;
            }
        }
        if !self.accept(TokKind::Rp, None) {
            return None;
        }
        Some(Stmt::Insert { table, vals })
    }

    fn parse_select(&mut self) -> Option<Stmt> {
        let mut star = false;
        let mut cols = Vec::new();
        if self.accept(TokKind::Star, None) {
            star = true;
        } else {
            loop {
                let mut rc = ResultCol { col: None, star: false };
                if self.accept(TokKind::Star, None) {
                    rc.star = true;
                } else if self.t[self.i].kind == TokKind::Id || self.t[self.i].kind == TokKind::Kw {
                    let mut buf = self.t[self.i].text.clone();
                    self.i += 1;
                    if self.t[self.i].kind == TokKind::Dot {
                        self.i += 1;
                        if self.accept(TokKind::Star, None) {
                            rc.star = true;
                        } else {
                            buf.push('.');
                            buf.push_str(&self.t[self.i].text);
                            self.i += 1;
                            rc.col = Some(buf);
                        }
                    } else {
                        rc.col = Some(buf);
                    }
                } else {
                    return None;
                }
                cols.push(rc);
                if !self.accept(TokKind::Comma, None) {
                    break;
                }
            }
        }
        if !self.accept_kw("from") {
            return None;
        }
        if self.t[self.i].kind != TokKind::Id {
            return None;
        }
        let mut tables = Vec::new();
        // first table
        let tname = self.t[self.i].text.clone();
        self.i += 1;
        let alias = if self.t[self.i].kind == TokKind::Id
            && !self.peek_kw("on")
            && !self.peek_kw("where")
            && !self.peek_kw("order")
            && !self.peek_kw("inner")
            && !self.peek_kw("join")
        {
            let a = self.t[self.i].text.clone();
            self.i += 1;
            Some(a)
        } else {
            None
        };
        tables.push(TableRef { tname, alias });

        let mut join_on: Option<Expr> = None;
        while self.peek_kw("inner") || self.peek_kw("join") {
            if self.accept_kw("inner") {
                if !self.accept_kw("join") {
                    return None;
                }
            } else {
                self.accept_kw("join");
            }
            if self.t[self.i].kind != TokKind::Id {
                return None;
            }
            let tname = self.t[self.i].text.clone();
            self.i += 1;
            let alias = if self.t[self.i].kind == TokKind::Id
                && !self.peek_kw("on")
                && !self.peek_kw("where")
                && !self.peek_kw("order")
            {
                let a = self.t[self.i].text.clone();
                self.i += 1;
                Some(a)
            } else {
                None
            };
            tables.push(TableRef { tname, alias });
            if self.accept_kw("on") {
                let on = self.parse_expr()?;
                join_on = Some(match join_on {
                    None => on,
                    Some(existing) => {
                        Expr::BinOp("AND".into(), Box::new(existing), Box::new(on))
                    }
                });
            }
        }

        let where_ = if self.accept_kw("where") {
            self.parse_expr()
        } else {
            None
        };

        let mut order_col = None;
        let mut order_desc = false;
        if self.accept_kw("order") {
            if !self.accept_kw("by") {
                return None;
            }
            if self.t[self.i].kind != TokKind::Id && self.t[self.i].kind != TokKind::Kw {
                return None;
            }
            order_col = Some(self.t[self.i].text.clone());
            self.i += 1;
            if self.accept_kw("desc") {
                order_desc = true;
            } else {
                self.accept_kw("asc");
            }
        }

        Some(Stmt::Select {
            cols,
            star,
            tables,
            where_,
            order_col,
            order_desc,
            join_on,
        })
    }

    fn parse(&mut self) -> Option<Stmt> {
        if self.peek_kw("begin") {
            self.i += 1;
            self.accept_kw("transaction");
            Some(Stmt::Begin)
        } else if self.peek_kw("commit") {
            self.i += 1;
            self.accept_kw("transaction");
            Some(Stmt::Commit)
        } else if self.accept_kw("create") {
            if self.accept_kw("table") {
                self.parse_create()
            } else {
                None
            }
        } else if self.accept_kw("insert") {
            self.parse_insert()
        } else if self.accept_kw("select") {
            self.parse_select()
        } else {
            None
        }
    }
}

// ---------- Database ----------
pub struct Sqlite3 {
    tables: Vec<Table>,
    stores: Vec<RowStore>,
    errmsg: String,
    in_txn: bool,
}

impl Sqlite3 {
    pub fn open(_name: &str) -> Sqlite3 {
        Sqlite3 {
            tables: Vec::new(),
            stores: Vec::new(),
            errmsg: String::new(),
            in_txn: false,
        }
    }

    pub fn close(self) {}

    pub fn errmsg(&self) -> &str {
        &self.errmsg
    }

    fn schema_find(&self, name: &str) -> Option<usize> {
        self.tables.iter().position(|t| t.name.eq_ignore_ascii_case(name))
    }

    fn exec_create(&mut self, name: &str, cols: Vec<String>) -> i32 {
        if self.schema_find(name).is_some() {
            self.errmsg = format!("table already exists: {}", name);
            return -1;
        }
        self.tables.push(Table { name: name.to_string(), cols });
        self.stores.push(RowStore { rows: Vec::new() });
        0
    }

    fn exec_insert(&mut self, table: &str, vals: Vec<Value>) -> i32 {
        match self.schema_find(table) {
            Some(idx) => {
                self.stores[idx].rows.push(vals);
                0
            }
            None => {
                self.errmsg = format!("no such table: {}", table);
                -1
            }
        }
    }

    pub fn exec<F>(&mut self, sql: &str, mut cb: F) -> i32
    where
        F: FnMut(i32, Vec<String>),
    {
        let toks = lex(sql);
        let mut p = Parser { t: toks, i: 0 };
        let mut rc = 0;
        while p.peek().kind != TokKind::Eof {
            match p.parse() {
                None => {
                    self.errmsg = "parse error".to_string();
                    rc = 1;
                    break;
                }
                Some(stmt) => {
                    match stmt {
                        Stmt::Begin => self.in_txn = true,
                        Stmt::Commit => self.in_txn = false,
                        Stmt::Create { name, cols } => {
                            rc = self.exec_create(&name, cols);
                        }
                        Stmt::Insert { table, vals } => {
                            rc = self.exec_insert(&table, vals);
                        }
                        Stmt::Select { .. } => {
                            let mut s = StmtObj::new(self, stmt);
                            while s.step(self) == 100 {
                                let vals: Vec<String> =
                                    (0..s.nout).map(|i| s.outrow[i].to_text()).collect();
                                cb(s.nout as i32, vals);
                            }
                        }
                    }
                    if rc != 0 {
                        break;
                    }
                }
            }
            p.accept(TokKind::Semi, None);
        }
        rc
    }

    pub fn prepare(&mut self, sql: &str) -> Option<StmtObj> {
        let toks = lex(sql);
        let mut p = Parser { t: toks, i: 0 };
        match p.parse() {
            None => {
                self.errmsg = "parse error".to_string();
                None
            }
            Some(stmt) => Some(StmtObj::new(self, stmt)),
        }
    }
}

// ---------- RowCtx / eval ----------
struct RowCtx<'a> {
    refs: &'a [TableRef],
    tabs: &'a [Table],
    rows: &'a [Row],
}

impl<'a> RowCtx<'a> {
    fn colindex(&self, col: &str) -> Option<(usize, usize)> {
        if let Some(dot) = col.find('.') {
            let tname = &col[..dot];
            let cname = &col[dot + 1..];
            for i in 0..self.refs.len() {
                let tn = self.refs[i].alias.as_ref().unwrap_or(&self.refs[i].tname);
                if tn.eq_ignore_ascii_case(tname) {
                    if let Some(ci) = self.tabs[i].colindex(cname) {
                        return Some((i, ci));
                    }
                }
            }
            None
        } else {
            for i in 0..self.refs.len() {
                if let Some(ci) = self.tabs[i].colindex(col) {
                    return Some((i, ci));
                }
            }
            None
        }
    }
}

fn eval_expr(e: &Expr, c: &RowCtx) -> Value {
    match e {
        Expr::Int(i) => Value::Int(*i),
        Expr::Str(s) => Value::Text(s.clone()),
        Expr::Col(col) => match c.colindex(col) {
            Some((ti, ci)) => c.rows[ti][ci].clone(),
            None => Value::Null,
        },
        Expr::BinOp(op, l, r) => {
            let a = eval_expr(l, c);
            let b = eval_expr(r, c);
            if op.eq_ignore_ascii_case("AND") {
                Value::Int((a.truthy() && b.truthy()) as i64)
            } else if op.eq_ignore_ascii_case("OR") {
                Value::Int((a.truthy() || b.truthy()) as i64)
            } else {
                let cmp = a.cmp(&b);
                let res = match op.as_str() {
                    "=" => cmp == std::cmp::Ordering::Equal,
                    "<>" => cmp != std::cmp::Ordering::Equal,
                    "<" => cmp == std::cmp::Ordering::Less,
                    ">" => cmp == std::cmp::Ordering::Greater,
                    "<=" => cmp != std::cmp::Ordering::Greater,
                    ">=" => cmp != std::cmp::Ordering::Less,
                    _ => false,
                };
                Value::Int(res as i64)
            }
        }
    }
}

fn row_match(e: Option<&Expr>, c: &RowCtx) -> bool {
    match e {
        None => true,
        Some(e) => eval_expr(e, c).truthy(),
    }
}

// ---------- Prepared statement ----------
pub struct StmtObj {
    stmt: Stmt,
    started: bool,
    done: bool,
    outrow: Vec<Value>,
    nout: usize,
    sorted: Vec<Row>,
    cur_sorted: usize,
}

impl StmtObj {
    fn new(_db: &Sqlite3, stmt: Stmt) -> StmtObj {
        StmtObj {
            stmt,
            started: false,
            done: false,
            outrow: Vec::new(),
            nout: 0,
            sorted: Vec::new(),
            cur_sorted: 0,
        }
    }

    fn collect_matching(&mut self, db: &Sqlite3) {
        if let Stmt::Select { ref tables, ref where_, ref join_on, ref order_col, ref order_desc, .. } = self.stmt {
            let n = tables.len();
            let idxs: Vec<Option<usize>> = tables.iter().map(|t| db.schema_find(&t.tname)).collect();
            let tabs: Vec<&Table> = idxs.iter().map(|i| i.map(|x| &db.tables[x]).unwrap_or(&db.tables[0])).collect();
            // nested loop
            let mut cur: Vec<usize> = vec![0; n];
            let sizes: Vec<usize> = (0..n).map(|i| idxs[i].map(|x| db.stores[x].rows.len()).unwrap_or(0)).collect();

            loop {
                // check all valid
                let mut ok = true;
                for i in 0..n {
                    if cur[i] >= sizes[i] {
                        ok = false;
                        break;
                    }
                }
                if !ok {
                    break;
                }
                let rows: Vec<Row> = (0..n).map(|i| db.stores[idxs[i].unwrap()].rows[cur[i]].clone()).collect();
                let ctx = RowCtx { refs: tables, tabs: &tabs, rows: &rows };
                if row_match(where_.as_ref(), &ctx) && row_match(join_on.as_ref(), &ctx) {
                    let combined: Row = rows.iter().flat_map(|r| r.iter().cloned()).collect();
                    self.sorted.push(combined);
                }
                // advance innermost
                let mut k = n as i64 - 1;
                while k >= 0 {
                    let ki = k as usize;
                    cur[ki] += 1;
                    if cur[ki] < sizes[ki] {
                        break;
                    }
                    if k > 0 {
                        cur[ki] = 0;
                        k -= 1;
                    } else {
                        k = -1;
                        break;
                    }
                }
                if k < 0 {
                    break;
                }
            }

            // ORDER BY
            if let Some(oc) = order_col {
                if n == 1 {
                    if let Some(cidx) = tabs[0].colindex(oc) {
                        self.sorted.sort_by(|a, b| {
                            let cmp = a[cidx].cmp(&b[cidx]);
                            if *order_desc {
                                cmp.reverse()
                            } else {
                                cmp
                            }
                        });
                    }
                }
            }
        }
    }

    pub fn step(&mut self, db: &Sqlite3) -> i32 {
        match self.stmt {
            Stmt::Select { .. } => {
                if !self.started {
                    self.started = true;
                    self.collect_matching(db);
                }
                if self.cur_sorted >= self.sorted.len() {
                    return 101;
                }
                let r = self.sorted[self.cur_sorted].clone();
                self.cur_sorted += 1;

                if let Stmt::Select { ref cols, star, ref tables, .. } = self.stmt {
                    let n = tables.len();
                    let idxs: Vec<Option<usize>> = tables.iter().map(|t| db.schema_find(&t.tname)).collect();
                    let tabs: Vec<&Table> = idxs.iter().map(|i| i.map(|x| &db.tables[x]).unwrap_or(&db.tables[0])).collect();
                    let mut offsets = Vec::new();
                    let mut off = 0;
                    for i in 0..n {
                        offsets.push(off);
                        off += tabs[i].cols.len();
                    }

                    self.outrow.clear();
                    if star {
                        for i in 0..n {
                            for j in 0..tabs[i].cols.len() {
                                self.outrow.push(r[offsets[i] + j].clone());
                            }
                        }
                    } else {
                        for rc in cols {
                            if rc.star {
                                for i in 0..n {
                                    for j in 0..tabs[i].cols.len() {
                                        self.outrow.push(r[offsets[i] + j].clone());
                                    }
                                }
                            } else if let Some(col) = &rc.col {
                                let mut found = false;
                                if let Some(dot) = col.find('.') {
                                    let tname = &col[..dot];
                                    let cname = &col[dot + 1..];
                                    for i in 0..n {
                                        let tn = tables[i].alias.as_ref().unwrap_or(&tables[i].tname);
                                        if tn.eq_ignore_ascii_case(tname) {
                                            if let Some(ci) = tabs[i].colindex(cname) {
                                                self.outrow.push(r[offsets[i] + ci].clone());
                                                found = true;
                                                break;
                                            }
                                        }
                                    }
                                } else {
                                    for i in 0..n {
                                        if let Some(ci) = tabs[i].colindex(col) {
                                            self.outrow.push(r[offsets[i] + ci].clone());
                                            found = true;
                                            break;
                                        }
                                    }
                                }
                                if !found {
                                    self.outrow.push(Value::Null);
                                }
                            }
                        }
                    }
                    self.nout = self.outrow.len();
                }
                100
            }
            _ => 101,
        }
    }

    pub fn column_count(&self) -> i32 {
        self.nout as i32
    }

    pub fn column_text(&self, i: i32) -> String {
        if i < 0 || i as usize >= self.nout {
            return String::new();
        }
        self.outrow[i as usize].to_text()
    }

    pub fn column_int64(&self, i: i32) -> i64 {
        if i < 0 || i as usize >= self.nout {
            return 0;
        }
        match &self.outrow[i as usize] {
            Value::Int(v) => *v,
            _ => 0,
        }
    }

    pub fn finalize(self) {}
}

// ---------- Demo ----------
fn print_row(_arg: &(), n: i32, vals: Vec<String>) {
    for i in 0..n as usize {
        print!("{}", vals[i]);
        if i + 1 < n as usize {
            print!(" | ");
        } else {
            println!();
        }
    }
}

fn main() {
    let mut db = Sqlite3::open(":memory:");
    let sql = "CREATE TABLE users (id INTEGER, name TEXT);\
               INSERT INTO users VALUES (1, 'ada');\
               INSERT INTO users VALUES (2, 'grace');\
               INSERT INTO users VALUES (3, 'linus');\
               SELECT * FROM users WHERE id > 1 ORDER BY id DESC;";
    let rc = db.exec(sql, |n, vals| print_row(&(), n, vals));
    if rc != 0 {
        eprintln!("err: {}", db.errmsg());
    }
    db.close();
}
