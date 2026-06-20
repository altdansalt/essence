class Sqlite3:
    def open(name=":memory:"): -> Sqlite3  (static/class method)
    def exec(sql, cb=None, arg=None): -> int (rc)
    def prepare(sql, n=-1): -> Stmt or None
    def close(): -> int
    def errmsg(): -> str

class Stmt:
    def step(): -> int (100=ROW, 101=DONE)
    def finalize(): -> int
    def column_count(): -> int
    def column_text(i): -> str
    def column_int64(i): -> int
