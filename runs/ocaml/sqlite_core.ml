(* Row context for expression evaluation *)
type row_ctx = {
  refs: table_ref list;
  tabs: table list;
  rows: row array;
}

let rowctx_colindex ctx col =
  match String.index_opt col '.' with
  | Some di ->
    let tname = String.sub col 0 di in
    let cname = String.sub col (di+1) (String.length col - di - 1) in
    let lt = String.lowercase_ascii tname in
    let rec aux i refs tabs =
      match refs, tabs with
      | r :: rs, t :: ts ->
        let tn = match r.alias with Some a -> a | None -> r.tname in
        if String.lowercase_ascii tn = lt then
          let ci = colindex t cname in
          if ci >= 0 then Some (i, ci) else None
        else aux (i+1) rs ts
      | _ -> None
    in aux 0 ctx.refs ctx.tabs
  | None ->
    let rec aux i refs tabs =
      match refs, tabs with
      | _, t :: ts ->
        let ci = colindex t col in
        if ci >= 0 then Some (i, ci) else aux (i+1) refs ts
      | _ -> None
    in aux 0 ctx.refs ctx.tabs

let rec eval_expr e ctx =
  match e with
  | EInt i -> VInt i
  | EStr s -> VText s
  | ECol col ->
    (match rowctx_colindex ctx col with
     | Some (ti, ci) -> v_copy ctx.rows.(ti).(ci)
     | None -> VNull)
  | EBinop (op, l, r) ->
    let a = eval_expr l ctx in
    let b = eval_expr r ctx in
    let op_u = String.uppercase_ascii op in
    if op_u = "AND" then VInt (if v_truthy a && v_truthy b then 1 else 0)
    else if op_u = "OR" then VInt (if v_truthy a || v_truthy b then 1 else 0)
    else begin
      let c = v_cmp a b in
      VInt (match op with
        | "=" | "==" -> if c=0 then 1 else 0
        | "<>" | "!=" -> if c<>0 then 1 else 0
        | "<" -> if c<0 then 1 else 0
        | ">" -> if c>0 then 1 else 0
        | "<=" -> if c<=0 then 1 else 0
        | ">=" -> if c>=0 then 1 else 0
        | _ -> 0)
    end

let row_match where ctx =
  match where with None -> true | Some e -> v_truthy (eval_expr e ctx)
