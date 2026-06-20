open System
open System.Text

// ---------- Value ----------
type VType = VNull | VInt | VText
type Value =
    | VNull
    | VInt of int64
    | VText of string

let vCopy = function VText s -> VText s | v -> v

let vCmp a b =
    match a, b with
    | VNull, VNull -> 0
    | VInt x, VInt y -> compare x y
    | VText x, VText y -> compare x y
    | VNull, _ -> -1
    | _, VNull -> 1
    | VInt _, VText _ -> -1
    | VText _, VInt _ -> 1

let vToText = function VInt i -> string i | VText s -> s | VNull -> "NULL"

let vTruthy v = vCmp v (VInt 0L) <> 0

// ---------- Schema ----------
type Table = { name: string; cols: string[] }
type Schema = { mutable tables: Table[] }
let schemaFind (s: Schema) name =
    s.tables |> Array.tryFind (fun t -> String.Equals(t.name, name, StringComparison.OrdinalIgnoreCase))
let schemaIndex (s: Schema) name =
    s.tables |> Array.tryFindIndex (fun t -> String.Equals(t.name, name, StringComparison.OrdinalIgnoreCase))
let schemaAdd (s: Schema) name cols =
    if schemaFind s name |> Option.isSome then -1
    else
        s.tables <- Array.append s.tables [|{ name = name; cols = cols }|]
        0
let tableColIndex (t: Table) col =
    t.cols |> Array.tryFindIndex (fun c -> String.Equals(c, col, StringComparison.OrdinalIgnoreCase))

// ---------- Row / store ----------
type Row = { vals: Value[] }
type RowStore = { mutable rows: Row list }

// ---------- Lexer ----------
type TokKind = TkEof | TkId | TkInt | TkString | TkKw | TkPunct | TkStar | TkComma | TkLp | TkRp | TkSemi | TkOp | TkDot
type Token = { kind: TokKind; text: string }

let keywords = set [
    "create";"table";"insert";"into";"values";"select";"from";"where";
    "order";"by";"asc";"desc";"and";"or";"not";"null";"begin";"commit";
    "inner";"join";"on";"int";"integer";"text";"primary";"key";"transaction"
]
let isKw s = keywords.Contains(String.ToLowerInvariant s)

let lex (sql: string) =
    let toks = ResizeArray<Token>()
    let n = sql.Length
    let i = ref 0
    let push k t = toks.Add { kind = k; text = t }
    while !i < n do
        let c = sql.[!i]
        if Char.IsWhiteSpace c then incr i
        elif c = '-' && !i+1 < n && sql.[!i+1] = '-' then
            while !i < n && sql.[!i] <> '\n' do incr i
        elif Char.IsLetter c || c = '_' then
            let st = !i
            while !i < n && (Char.IsLetterOrDigit sql.[!i] || sql.[!i] = '_') do incr i
            let s = sql.[st..!i-1]
            push (if isKw s then TkKw else TkId) s
        elif Char.IsDigit c then
            let st = !i
            while !i < n && Char.IsDigit sql.[!i] do incr i
            push TkInt (sql.[st..!i-1])
        elif c = '\'' then
            incr i
            let st = !i
            while !i < n && sql.[!i] <> '\'' do incr i
            push TkString (sql.[st..!i-1])
            if !i < n && sql.[!i] = '\'' then incr i
        elif c = '"' then
            incr i
            let st = !i
            while !i < n && sql.[!i] <> '"' do incr i
            push TkId (sql.[st..!i-1])
            if !i < n && sql.[!i] = '"' then incr i
        else
            match c with
            | '*' -> push TkStar "*"; incr i
            | ',' -> push TkComma ","; incr i
            | '(' -> push TkLp "("; incr i
            | ')' -> push TkRp ")"; incr i
            | ';' -> push TkSemi ";"; incr i
            | '.' -> push TkDot "."; incr i
            | _ when "=<>!".Contains(string c) ->
                let st = !i
                if !i+1 < n && sql.[!i+1] = '=' then incr i
                if c = '<' && !i+1 < n && sql.[!i+1] = '>' then incr i
                if c = '!' && !i+1 < n && sql.[!i+1] = '=' then incr i
                incr i
                push TkOp (sql.[st..!i-1])
            | _ -> push TkPunct (string c); incr i
    push TkEof ""
    toks.ToArray()

// ---------- AST ----------
type Expr =
    | ECol of string
    | EInt of int64
    | EStr of string
    | EBinop of string * Expr * Expr

type ResultCol = { col: string option; star: bool }
type TableRef = { tname: string; alias: string option }

type Stmt =
    | SCreate of name: string * cols: string[]
    | SInsert of table: string * vals: Value[]
    | SSelect of cols: ResultCol[] * star: bool * tables: TableRef[] * whereExpr: Expr option * orderCol: string option * orderDesc: bool * joinOn: Expr option
    | SBegin
    | SCommit

// ---------- Parser ----------
type Parser(toks: Token[]) =
    let i = ref 0
    member _.T = toks
    member _.I = i
    member _.Cur = toks.[!i]
    member _.Advance() = incr i
    member _.Accept k text =
        if toks.[!i].kind <> k then false
        elif text <> null && not(String.Equals(toks.[!i].text, text, StringComparison.OrdinalIgnoreCase)) then false
        else incr i; true
    member _.AcceptKw kw = p.Accept TkKw kw
    member _.PeekKw kw =
        toks.[!i].kind = TkKw && String.Equals(toks.[!i].text, kw, StringComparison.OrdinalIgnoreCase)
    member _.PeekKind k = toks.[!i].kind = k

let parsePrimary (p: Parser) =
    let t = p.Cur
    match t.kind with
    | TkInt -> p.Advance(); EInt (int64 t.text)
    | TkString -> p.Advance(); EStr t.text
    | TkId | TkKw ->
        let buf = StringBuilder(t.text)
        p.Advance()
        if p.PeekKind TkDot then
            p.Advance()
            buf.Append('.').Append(p.Cur.text) |> ignore
            p.Advance()
        ECol (buf.ToString())
    | _ when p.Accept TkLp null ->
        let e = parseExpr p
        p.Accept TkRp null |> ignore
        e
    | _ -> failwith "parse error: expected primary"
and parseCmp (p: Parser) =
    let l = parsePrimary p
    if p.PeekKind TkOp then
        let op = p.Cur.text
        p.Advance()
        EBinop (op, l, parsePrimary p)
    else l
and parseExpr (p: Parser) =
    let l = parseCmp p
    if p.PeekKw "and" || p.PeekKw "or" then
        let op = if p.PeekKw "and" then "AND" else "OR"
        p.Advance()
        EBinop (op, l, parseExpr p)
    else l

let parseCreate (p: Parser) =
    let name = p.Cur.text
    p.Advance()
    if not (p.Accept TkLp null) then failwith "parse error: expected ("
    let cols = ResizeArray<string>()
    while p.Cur.kind <> TkRp && p.Cur.kind <> TkEof do
        if p.Cur.kind <> TkId && p.Cur.kind <> TkKw then failwith "parse error: expected column name"
        cols.Add p.Cur.text
        p.Advance()
        while p.Cur.kind <> TkComma && p.Cur.kind <> TkRp && p.Cur.kind <> TkEof do p.Advance()
        p.Accept TkComma null |> ignore
    p.Accept TkRp null |> ignore
    SCreate (name, cols.ToArray())

let parseInsert (p: Parser) =
    if not (p.AcceptKw "into") then failwith "parse error: expected INTO"
    if p.Cur.kind <> TkId then failwith "parse error: expected table name"
    let table = p.Cur.text
    p.Advance()
    if not (p.AcceptKw "values") then failwith "parse error: expected VALUES"
    if not (p.Accept TkLp null) then failwith "parse error: expected ("
    let vals = ResizeArray<Value>()
    while p.Cur.kind <> TkRp && p.Cur.kind <> TkEof do
        let v =
            match p.Cur.kind with
            | TkInt -> VInt (int64 p.Cur.text)
            | TkString -> VText p.Cur.text
            | TkKw when String.Equals(p.Cur.text, "null", StringComparison.OrdinalIgnoreCase) -> VNull
            | _ -> failwith "parse error: expected value"
        p.Advance()
        vals.Add v
        if not (p.Accept TkComma null) then ()
    p.Accept TkRp null |> ignore
    SInsert (table, vals.ToArray())

let parseSelect (p: Parser) =
    let mutable star = false
    let cols = ResizeArray<ResultCol>()
    if p.Accept TkStar null then
        star <- true
    else
        let mutable cont = true
        while cont do
            let rc = { col = None; star = false }
            if p.Accept TkStar null then
                cols.Add { rc with star = true }
            elif p.Cur.kind = TkId || p.Cur.kind = TkKw then
                let buf = StringBuilder(p.Cur.text)
                p.Advance()
                if p.PeekKind TkDot then
                    p.Advance()
                    if p.Accept TkStar null then
                        cols.Add { col = None; star = true }
                    else
                        buf.Append('.').Append(p.Cur.text) |> ignore
                        p.Advance()
                        cols.Add { col = Some (buf.ToString()); star = false }
                else
                    cols.Add { col = Some (buf.ToString()); star = false }
            else
                failwith "parse error: expected column"
            cont <- p.Accept TkComma null
    if not (p.AcceptKw "from") then failwith "parse error: expected FROM"
    if p.Cur.kind <> TkId then failwith "parse error: expected table name"
    let tables = ResizeArray<TableRef>()
    let isStopKw () =
        p.PeekKw "on" || p.PeekKw "where" || p.PeekKw "order" || p.PeekKw "inner" || p.PeekKw "join"
    // first table
    let tname = p.Cur.text
    p.Advance()
    let alias =
        if p.Cur.kind = TkId && not (isStopKw ()) then
            let a = p.Cur.text
            p.Advance()
            Some a
        else None
    tables.Add { tname = tname; alias = alias }
    let mutable joinOn = None
    while p.PeekKw "inner" || p.PeekKw "join" do
        if p.AcceptKw "inner" then
            if not (p.AcceptKw "join") then failwith "parse error: expected JOIN"
        else
            p.AcceptKw "join" |> ignore
        if p.Cur.kind <> TkId then failwith "parse error: expected table name"
        let tn = p.Cur.text
        p.Advance()
        let al =
            if p.Cur.kind = TkId && not (p.PeekKw "on" || p.PeekKw "where" || p.PeekKw "order") then
                let a = p.Cur.text
                p.Advance()
                Some a
            else None
        tables.Add { tname = tn; alias = al }
        if p.AcceptKw "on" then
            let on = parseExpr p
            joinOn <- match joinOn with None -> Some on | Some prev -> Some (EBinop("AND", prev, on))
    let whereExpr = if p.AcceptKw "where" then Some (parseExpr p) else None
    let orderCol, orderDesc =
        if p.AcceptKw "order" then
            if not (p.AcceptKw "by") then failwith "parse error: expected BY"
            if p.Cur.kind <> TkId && p.Cur.kind <> TkKw then failwith "parse error: expected column"
            let c = p.Cur.text
            p.Advance()
            if p.AcceptKw "desc" then Some c, true
            else p.AcceptKw "asc" |> ignore; Some c, false
        else None, false
    SSelect (cols.ToArray(), star, tables.ToArray(), whereExpr, orderCol, orderDesc, joinOn)

let parse (toks: Token[]) =
    let p = Parser(toks)
    let stmt =
        if p.PeekKw "begin" then
            p.Advance(); p.AcceptKw "transaction" |> ignore; SBegin
        elif p.PeekKw "commit" then
            p.Advance(); p.AcceptKw "transaction" |> ignore; SCommit
        elif p.AcceptKw "create" then
            if p.AcceptKw "table" then parseCreate p else failwith "parse error: expected TABLE"
        elif p.AcceptKw "insert" then parseInsert p
        elif p.AcceptKw "select" then parseSelect p
        else failwith "parse error"
    p.Accept TkSemi null |> ignore
    stmt

let parseAll (sql: string) =
    let toks = lex sql
    let stmts = ResizeArray<Stmt>()
    let p = Parser(toks)
    while p.Cur.kind <> TkEof do
        let s =
            if p.PeekKw "begin" then p.Advance(); p.AcceptKw "transaction" |> ignore; SBegin
            elif p.PeekKw "commit" then p.Advance(); p.AcceptKw "transaction" |> ignore; SCommit
            elif p.AcceptKw "create" then if p.AcceptKw "table" then parseCreate p else failwith "parse error: expected TABLE"
            elif p.AcceptKw "insert" then parseInsert p
            elif p.AcceptKw "select" then parseSelect p
            else failwith "parse error"
        p.Accept TkSemi null |> ignore
        stmts.Add s
    stmts.ToArray()

// ---------- Database ----------
type sqlite3() =
    let schema = { tables = [||] }
    let stores = ResizeArray<RowStore>()
    let mutable errmsg = ""
    let mutable inTxn = false
    member _.Schema = schema
    member _.Stores = stores
    member val Errmsg = "" with get, set
    member _.InTxn with get() = inTxn and set v = inTxn <- v

// ---------- expression eval ----------
type RowCtx = { refs: TableRef[]; tabs: Table[]; rows: Row[] }

let rowctxColindex (c: RowCtx) (col: string) =
    let dot = col.IndexOf('.')
    if dot >= 0 then
        let tname = col.[..dot-1]
        let cname = col.[dot+1..]
        c.refs |> Array.mapi (fun i r ->
            let tn = r.alias |> Option.defaultValue r.tname
            if String.Equals(tn, tname, StringComparison.OrdinalIgnoreCase) then
                match tableColindex c.tabs.[i] cname with
                | Some ci -> Some (i, ci)
                | None -> None
            else None)
        |> Array.tryPick id
    else
        c.tabs |> Array.mapi (fun i t ->
            match tableColindex t col with
            | Some ci -> Some (i, ci) | None -> None)
        |> Array.tryPick id

let rec evalExpr (e: Expr) (c: RowCtx) =
    match e with
    | EInt i -> VInt i
    | EStr s -> VText s
    | ECol col ->
        match rowctxColindex c col with
        | Some (ti, ci) -> vCopy c.rows.[ti].vals.[ci]
        | None -> VNull
    | EBinop (op, l, r) ->
        let a = evalExpr l c
        let b = evalExpr r c
        if String.Equals(op, "AND", StringComparison.OrdinalIgnoreCase) then
            VInt (if vTruthy a && vTruthy b then 1L else 0L)
        elif String.Equals(op, "OR", StringComparison.OrdinalIgnoreCase) then
            VInt (if vTruthy a || vTruthy b then 1L else 0L)
        else
            let cmp = vCmp a b
            VInt (
                match op with
                | "=" -> if cmp = 0 then 1L else 0L
                | "<>" -> if cmp <> 0 then 1L else 0L
                | "<" -> if cmp < 0 then 1L else 0L
                | ">" -> if cmp > 0 then 1L else 0L
                | "<=" -> if cmp <= 0 then 1L else 0L
                | ">=" -> if cmp >= 0 then 1L else 0L
                | _ -> 0L)

let rowMatch whereExpr (c: RowCtx) =
    match whereExpr with
    | None -> true
    | Some e -> vTruthy (evalExpr e c)

// ---------- prepared statement ----------
type sqlite3_stmt(db: sqlite3, st: Stmt) =
    let mutable started = false
    let mutable done_ = false
    let mutable sorted: Row[] = [||]
    let mutable curSorted = 0
    let mutable outrow: Value[] = [||]
    let mutable nout = 0
    member _.Stmt = st
    member _.Db = db
    member _.Outrow = outrow
    member _.Nout = nout
    member _.Outrow with set v = outrow <- v
    member _.Nout with set v = nout <- v

    member s.CollectMatching() =
        match st with
        | SSelect (_, _, tables, whereExpr, orderCol, orderDesc, joinOn) ->
            let n = tables.Length
            let idxs = tables |> Array.map (fun t -> schemaIndex db.Schema t.tname)
            let tabs = idxs |> Array.map (fun i -> match i with Some idx -> db.Schema.tables.[idx] | None -> { name=""; cols=[||] })
            let storeRows = idxs |> Array.map (fun i -> match i with Some idx -> db.Stores.[idx].rows | None -> [])
            // nested loop
            let results = ResizeArray<Row>()
            let rec loop depth curs =
                if depth = n then
                    let rows = curs |> Array.map (fun r -> r)
                    let ctx = { refs = tables; tabs = tabs; rows = rows }
                    if rowMatch whereExpr ctx && rowMatch joinOn ctx then
                        let combined = tabs |> Array.mapi (fun i t -> storeRows.[i] |> List.length) |> ignore
                        let vals = [|
                            for i in 0..n-1 do
                                for j in 0..tabs.[i].cols.Length-1 do
                                    vCopy curs.[i].vals.[j]
                        |]
                        results.Add { vals = vals }
                else
                    let rows = match idxs.[depth] with Some idx -> db.Stores.[idx].rows | None -> []
                    for r in rows do
                        loop (depth+1) (Array.append curs [|r|])
            loop 0 [||]
            let mutable arr = results.ToArray()
            // ORDER BY
            orderCol |> Option.iter (fun oc ->
                if n = 1 then
                    match tableColIndex tabs.[0] oc with
                    | Some cidx ->
                        arr <- arr |> Array.sortInPlaceWith (fun a b ->
                            let c = vCmp a.vals.[cidx] b.vals.[cidx]
                            if orderDesc then -c else c)
                    | None -> ()
            )
            sorted <- arr
        | _ -> ()

    member s.StepSelect() =
        if not started then
            started <- true
            s.CollectMatching()
        if curSorted >= sorted.Length then 101
        else
            let r = sorted.[curSorted]
            curSorted <- curSorted + 1
            match st with
            | SSelect (cols, star, tables, _, _, _, _) ->
                let n = tables.Length
                let tabs = tables |> Array.map (fun t -> schemaFind db.Schema t.tname |> Option.defaultValue { name=""; cols=[||] })
                let offsets = Array.zeroCreate n
                let mutable off = 0
                for i in 0..n-1 do offsets.[i] <- off; off <- off + tabs.[i].cols.Length
                let outVals = ResizeArray<Value>()
                if star then
                    for i in 0..n-1 do
                        for j in 0..tabs.[i].cols.Length-1 do
                            outVals.Add (vCopy r.vals.[offsets.[i]+j])
                else
                    for k in 0..cols.Length-1 do
                        let rc = cols.[k]
                        if rc.star then
                            for i in 0..n-1 do
                                for j in 0..tabs.[i].cols.Length-1 do
                                    outVals.Add (vCopy r.vals.[offsets.[i]+j])
                        else
                            match rc.col with
                            | None -> outVals.Add VNull
                            | Some col ->
                                let dot = col.IndexOf('.')
                                let ti, ci =
                                    if dot >= 0 then
                                        let tname = col.[..dot-1]
                                        let cname = col.[dot+1..]
                                        let mutable found = (0, -1)
                                        for i in 0..n-1 do
                                            let tn = tables.[i].alias |> Option.defaultValue tables.[i].tname
                                            if String.Equals(tn, tname, StringComparison.OrdinalIgnoreCase) then
                                                match tableColIndex tabs.[i] cname with
                                                | Some c -> found <- (i, c)
                                                | None -> ()
                                        found
                                    else
                                        let mutable found = (0, -1)
                                        for i in 0..n-1 do
                                            match tableColIndex tabs.[i] col with
                                            | Some c -> found <- (i, c)
                                            | None -> ()
                                        found
                                if ci < 0 then outVals.Add VNull
                                else outVals.Add (vCopy r.vals.[offsets.[ti]+ci])
                outrow <- outVals.ToArray()
                nout <- outrow.Length
                100
            | _ -> 101

// ---------- public API ----------
type Sqlite3 =
    static member open_ (name: string) =
        let db = sqlite3()
        db

    static member close (db: sqlite3) = ()

    static member errmsg (db: sqlite3) = db.Errmsg

    static member exec (db: sqlite3) (sql: string) (cb: (int -> string[] -> unit) option) =
        let mutable rc = 0
        try
            let stmts = parseAll sql
            for st in stmts do
                match st with
                | SBegin -> db.InTxn <- true
                | SCommit -> db.InTxn <- false
                | SCreate (name, cols) ->
                    if schemaAdd db.Schema name cols <> 0 then
                        db.Errmsg <- sprintf "table already exists: %s" name
                        rc <- 1
                    else
                        db.Stores.Add { rows = [] }
                | SInsert (table, vals) ->
                    match schemaIndex db.Schema table with
                    | None ->
                        db.Errmsg <- sprintf "no such table: %s" table
                        rc <- 1
                    | Some idx ->
                        db.Stores.[idx].rows <- db.Stores.[idx].rows @ [{ vals = vals |> Array.map vCopy }]
                | SSelect _ ->
                    use s = new sqlite3_stmt(db, st)
                    let mutable r = 0
                    while (r <- s.StepSelect(); r = 100) do
                        let vals = s.Outrow |> Array.map vToText
                        cb |> Option.iter (fun f -> f s.Nout vals)
                | _ -> ()
        with ex ->
            db.Errmsg <- ex.Message
            rc <- 1
        rc

    static member prepare_v2 (db: sqlite3) (sql: string) =
        let toks = lex sql
        let st = parse toks
        new sqlite3_stmt(db, st)

    static member step (s: sqlite3_stmt) =
        match s.Stmt with
        | SSelect _ -> s.StepSelect()
        | _ -> 101

    static member column_count (s: sqlite3_stmt) = s.Nout

    static member column_text (s: sqlite3_stmt) (i: int) =
        if i < 0 || i >= s.Nout then null
        else vToText s.Outrow.[i]

    static member column_int64 (s: sqlite3_stmt) (i: int) =
        if i < 0 || i >= s.Nout then 0L
        else match s.Outrow.[i] with VInt v -> v | _ -> 0L

    static member finalize (s: sqlite3_stmt) = ()

// ---------- demo ----------
[<EntryPoint>]
let main _ =
    let db = Sqlite3.open_ ":memory:"
    let sql =
        "CREATE TABLE users (id INTEGER, name TEXT);\
         INSERT INTO users VALUES (1, 'ada');\
         INSERT INTO users VALUES (2, 'grace');\
         INSERT INTO users VALUES (3, 'linus');\
         SELECT * FROM users WHERE id > 1 ORDER BY id DESC;"
    let printRow n vals =
        let line = vals |> Array.mapi (fun i v -> v + (if i+1 < n then " | " else "")) |> String.concat ""
        printfn "%s" line
    let rc = Sqlite3.exec db sql (Some printRow)
    if rc <> 0 then
        fprintfn stderr "err: %s" (Sqlite3.errmsg db)
    Sqlite3.close db
    0
