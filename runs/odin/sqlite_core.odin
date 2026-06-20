free_stmt :: proc(st: ^Stmt) {
    delete(st.ct_cols)
    delete(st.ins_vals)
    for i in 0..<len(st.sel_cols) {
        // sel_cols[i].col is a string, which is a slice - no need to free individually
    }
    delete(st.sel_cols)
    delete(st.sel_tables)
    free_expr(st.sel_where)
    free_expr(st.sel_join_on)
    // sel_order_col is a string, no need to free
}

free_expr :: proc(e: ^Expr) {
    if e == nil { return }
    free_expr(e.l)
    free_expr(e.r)
    free(e)
}
