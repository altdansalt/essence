defp exec_tokens(db, [{:eof, _} | _], _callback), do: {0, db}
defp exec_tokens(db, tokens, callback) do
  case parse_stmt(tokens) do
    {:ok, stmt, rest} ->
      {rc, db} = exec_stmt(db, stmt, callback)
      {final_rc, final_db} = exec_tokens(db, rest, callback)
      # If this statement set rc (create/insert), use it; otherwise use final_rc
      # But actually, the C code just overwrites rc each time for create/insert
      # and doesn't touch it for select/begin/commit
      # So the last create/insert rc wins, or 0 if no create/insert after it
      {rc_or_final, _} = case stmt.type do
        :create -> {rc, db}
        :insert -> {rc, db}
        _ -> {final_rc, final_db}
      end
      # Hmm, this is still not right...
  end
end
