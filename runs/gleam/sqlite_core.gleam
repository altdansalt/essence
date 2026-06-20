fn v_cmp(a: Value, b: Value) -> Int {
  case a, b {
    VNull, VNull -> 0
    VInt(x), VInt(y) -> case x < y { True -> -1; False -> case x > y { True -> 1; False -> 0 } }
    VText(x), VText(y) -> string.compare(x, y) |> order_to_int
    VNull, _ -> -1  // V_NULL=0, V_INT=1, V_TEXT=2, so 0-1=-1 or 0-2=-2
    _, VNull -> 1
    VInt(_), VText(_) -> -1  // 1-2=-1
    VText(_), VInt(_) -> 1   // 2-1=1
  }
}
