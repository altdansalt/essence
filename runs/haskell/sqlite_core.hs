data StmtState = StmtState
  { ssDB :: Sqlite3
  , ssStmt :: Stmt
  , ssSorted :: [[Value]]
  , ssCurIdx :: Int
  , ssOutRow :: [Value]
  , ssStarted :: Bool
  }
