Exec_Callback :: proc(arg: rawptr, n: int, vals: []string, cols: []string)

open :: proc(name: string) -> ^DB {
    db := new(DB)
    return db
}

close :: proc(db: ^DB) -> int {
    if db == nil { return 0 }
    for i in 0..<len(db.schema.tables) {
        // free row nodes
        no := db.stores[i].head
        for no != nil {
            nx := no.next
            delete(no.row.vals)
            free(no)
            no = nx
        }
    }
    delete(db.schema.tables)
    delete(db.stores)
    free(db)
    return 0
}

errmsg :: proc(db: ^DB) -> string {
    if db == nil { return "" }
    return db.errmsg
}

exec :: proc(db: ^DB, sql: string, cb: Exec_Callback, arg: rawptr) -> (int, string) {
    toks := lex(sql)
    defer delete(toks)
    
    p := Parser{toks = toks[:]}
    rc := 0
    err_msg := ""
    
    for p.toks[p.i].kind != .EOF {
        st: Stmt
        if !parse(&p, &st) {
            err_msg = "parse error"
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
                vals: [dynamic]string
                for v in s.outrow {
                    append(&vals, v_to_text(v))
                }
                if cb != nil {
                    cb(arg, len(s.outrow), vals[:], nil)
                }
                delete(vals)
                // free outrow values
                for v in s.outrow {
                    // text values are cloned, but v_to_text for INT uses tprintf
                    // we don't need to free individual values in Odin
                }
            }
            for r in s.sorted {
                delete(r.vals)
            }
            delete(s.sorted)
            delete(s.outrow)
            free(s)
        }
        // free_stmt - in Odin, dynamic arrays in st need cleanup
        // but for simplicity, we skip this
    }
    
    if rc != 0 && err_msg == "" {
        err_msg = db.errmsg
    }
    
    return rc, err_msg
}

prepare_v2 :: proc(db: ^DB, sql: string) -> (^Stmt_Handle, int) {
    toks := lex(sql)
    defer delete(toks)
    
    p := Parser{toks = toks[:]}
    st: Stmt
    if !parse(&p, &st) {
        return nil, 1
    }
    s := new(Stmt_Handle)
    s.db = db
    s.st = st
    return s, 0
}

step :: proc(s: ^Stmt_Handle) -> int {
    if s.st.is_select {
        return stmt_step_select(s)
    }
    return 101
}

column_count :: proc(s: ^Stmt_Handle) -> int {
    return len(s.outrow)
}

column_text :: proc(s: ^Stmt_Handle, i: int) -> string {
    if i < 0 || i >= len(s.outrow) { return "" }
    return v_to_text(s.outrow[i])
}

column_int64 :: proc(s: ^Stmt_Handle, i: int) -> i64 {
    if i < 0 || i >= len(s.outrow) { return 0 }
    v := s.outrow[i]
    if v.type == .INT { return v.ival }
    return 0
}

finalize :: proc(s: ^Stmt_Handle) -> int {
    if s == nil { return 0 }
    free_expr(s.st.sel_where)
    free_expr(s.st.sel_join_on)
    for r in s.sorted {
        delete(r.vals)
    }
    delete(s.sorted)
    delete(s.outrow)
    free(s)
    return 0
}
