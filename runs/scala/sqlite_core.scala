import scala.collection.mutable.ArrayBuffer

object Sqlite3 {
  // ---------- Value ----------
  sealed trait VType
  object VType { case object VNull extends VType; case object VInt extends VType; case object VText extends VType }
  case class Value(vtype: VType, ival: Long = 0, sval: String = "") {
    def copy: Value = vtype match {
      case VType.VText => Value(VType.VText, 0, sval)
      case _ => this
    }
  }
  def vNull: Value = Value(VType.VNull)
  def vInt(i: Long): Value = Value(VType.VInt, i)
  def vText(s: String): Value = Value(VType.VText, 0, if (s == null) "" else s)

  def vCmp(a: Value, b: Value): Int = {
    if (a.vtype != b.vtype) return a.vtype.ordinal - b.vtype.ordinal
    a.vtype match {
      case VType.VInt => a.ival.compareTo(b.ival)
      case VType.VText => a.sval.compareTo(b.sval)
      case _ => 0
    }
  }
  def vToText(v: Value): String = v.vtype match {
    case VType.VInt => v.ival.toString
    case VType.VText => v.sval
    case _ => "NULL"
  }
  def vTruthy(v: Value): Boolean = vCmp(v, vInt(0)) != 0

  // ---------- Schema ----------
  case class Table(name: String, cols: ArrayBuffer[String])
  class Schema {
    val tables = ArrayBuffer[Table]()
    def find(name: String): Option[Table] = tables.find(_.name.equalsIgnoreCase(name))
    def index(name: String): Int = tables.indexWhere(_.name.equalsIgnoreCase(name))
    def add(name: String, cols: ArrayBuffer[String]): Int = {
      if (find(name).isDefined) return -1
      tables += Table(name, cols)
      0
    }
    def colIndex(t: Table, col: String): Int = t.cols.indexWhere(_.equalsIgnoreCase(col))
  }

  // ---------- Row / store ----------
  case class Row(vals: ArrayBuffer[Value])
  class RowStore {
    val rows = ArrayBuffer[Row]()
    def nrows: Int = rows.size
  }

  // ---------- Lexer ----------
  sealed trait TokKind
  object TokKind {
    case object TKEof extends TokKind; case object TKId extends TokKind; case object TKInt extends TokKind
    case object TKString extends TokKind; case object TKKw extends TokKind; case object TKPunct extends TokKind
    case object TKStar extends TokKind; case object TKComma extends TokKind; case object TKLp extends TokKind
    case object TKRp extends TokKind; case object TKSemi extends TokKind; case object TKOp extends TokKind
    case object TKDot extends TokKind
  }
  case class Token(kind: TokKind, text: String)

  val KEYWORDS = Set("create","table","insert","into","values","select","from","where",
    "order","by","asc","desc","and","or","not","null","begin","commit",
    "inner","join","on","int","integer","text","primary","key","transaction")

  def lex(sql: String): ArrayBuffer[Token] = {
    val toks = ArrayBuffer[Token]()
    var pos = 0
    val s = sql
    def isAlpha(c: Char) = c.isLetter || c == '_'
    def isAlnum(c: Char) = c.isLetterOrDigit || c == '_'
    while (pos < s.length) {
      val c = s(pos)
      if (c.isWhitespace) { pos += 1 }
      else if (c == '-' && pos + 1 < s.length && s(pos + 1) == '-') {
        while (pos < s.length && s(pos) != '\n') pos += 1
      } else if (isAlpha(c)) {
        val st = pos
        while (pos < s.length && isAlnum(s(pos))) pos += 1
        val text = s.substring(st, pos)
        toks += Token(if (KEYWORDS.contains(text.toLowerCase)) TokKind.TKKw else TokKind.TKId, text)
      } else if (c.isDigit) {
        val st = pos
        while (pos < s.length && s(pos).isDigit) pos += 1
        toks += Token(TokKind.TKInt, s.substring(st, pos))
      } else if (c == '\'') {
        pos += 1; val st = pos
        while (pos < s.length && s(pos) != '\'') pos += 1
        toks += Token(TokKind.TKString, s.substring(st, pos))
        if (pos < s.length && s(pos) == '\'') pos += 1
      } else if (c == '"') {
        pos += 1; val st = pos
        while (pos < s.length && s(pos) != '"') pos += 1
        toks += Token(TokKind.TKId, s.substring(st, pos))
        if (pos < s.length && s(pos) == '"') pos += 1
      } else c match {
        case '*' => toks += Token(TokKind.TKStar, "*"); pos += 1
        case ',' => toks += Token(TokKind.TKComma, ","); pos += 1
        case '(' => toks += Token(TokKind.TKLp, "("); pos += 1
        case ')' => toks += Token(TokKind.TKRp, ")"); pos += 1
        case ';' => toks += Token(TokKind.TKSemi, ";"); pos += 1
        case '.' => toks += Token(TokKind.TKDot, "."); pos += 1
        case ch if "=<>!".contains(ch) =>
          val st = pos
          if (pos + 1 < s.length && s(pos + 1) == '=') pos += 1
          if (pos + 1 < s.length && c == '<' && s(pos + 1) == '>') pos += 1
          if (pos + 1 < s.length && c == '!' && s(pos + 1) == '=') pos += 1
          pos += 1
          toks += Token(TokKind.TKOp, s.substring(st, pos))
        case _ => toks += Token(TokKind.TKPunct, c.toString); pos += 1
      }
    }
    toks += Token(TokKind.TKEof, "")
    toks
  }

  // ---------- AST ----------
  sealed trait ExprKind
  object ExprKind { case object ECol extends ExprKind; case object EInt extends ExprKind; case object EStr extends ExprKind; case object EBinop extends ExprKind }
  sealed trait Expr
  object Expr {
    case class ECol(col: String) extends Expr
    case class EInt(ival: Long) extends Expr
    case class EStr(sval: String) extends Expr
    case class EBinop(op: String, l: Expr, r: Expr) extends Expr
  }

  case class ResultCol(col: String, star: Boolean)
  case class TableRef(tname: String, alias: String)

  case class Stmt(
    isCreate: Boolean = false, isInsert: Boolean = false, isSelect: Boolean = false,
    isBegin: Boolean = false, isCommit: Boolean = false,
    ctName: String = null, ctCols: ArrayBuffer[String] = null,
    insTable: String = null, insVals: ArrayBuffer[Value] = null,
    selCols: ArrayBuffer[ResultCol] = null, selStar: Boolean = false,
    selTables: ArrayBuffer[TableRef] = null,
    selWhere: Expr = null, selOrderCol: String = null, selOrderDesc: Boolean = false,
    selJoinOn: Expr = null
  )

  // ---------- Parser ----------
  class Parser(toks: ArrayBuffer[Token]) {
    var i = 0
    def cur: Token = toks(i)
    def accept(k: TokKind, text: String = null): Boolean = {
      if (cur.kind != k) return false
      if (text != null && !cur.text.equalsIgnoreCase(text)) return false
      i += 1; true
    }
    def acceptKw(kw: String): Boolean = accept(TokKind.TKKw, kw)
    def peekKw(kw: String): Boolean = cur.kind == TokKind.TKKw && cur.text.equalsIgnoreCase(kw)

    def parsePrimary: Expr = {
      val t = cur
      t.kind match {
        case TokKind.TKInt => i += 1; Expr.EInt(t.text.toLong)
        case TokKind.TKString => i += 1; Expr.EStr(t.text)
        case TokKind.TKId | TokKind.TKKw =>
          var buf = t.text; i += 1
          if (cur.kind == TokKind.TKDot) {
            i += 1; buf += "." + cur.text; i += 1
          }
          Expr.ECol(buf)
        case _ =>
          if (accept(TokKind.TKLp)) {
            val e = parseExpr; accept(TokKind.TKRp); e
          } else null
      }
    }

    def parseCmp: Expr = {
      val l = parsePrimary
      if (cur.kind == TokKind.TKOp) {
        val op = cur.text; i += 1
        val r = parsePrimary
        Expr.EBinop(op, l, r)
      } else l
    }

    def parseExpr: Expr = {
      val l = parseCmp
      if (peekKw("and") || peekKw("or")) {
        val op = if (peekKw("and")) "AND" else "OR"
        i += 1
        Expr.EBinop(op, l, parseExpr)
      } else l
    }

    def parseCreate(st: Stmt): Stmt = {
      if (cur.kind != TokKind.TKId && cur.kind != TokKind.TKKw) return st.copy()
      val name = cur.text; i += 1
      if (!accept(TokKind.TKLp)) return st.copy(isCreate = true, ctName = name)
      val cols = ArrayBuffer[String]()
      while (cur.kind != TokKind.TKRp && cur.kind != TokKind.TKEof) {
        if (cur.kind == TokKind.TKId || cur.kind == TokKind.TKKw) {
          cols += cur.text; i += 1
        }
        while (cur.kind != TokKind.TKComma && cur.kind != TokKind.TKRp && cur.kind != TokKind.TKEof) i += 1
        accept(TokKind.TKComma)
      }
      accept(TokKind.TKRp)
      st.copy(isCreate = true, ctName = name, ctCols = cols)
    }

    def parseInsert(st: Stmt): Stmt = {
      if (!acceptKw("into")) return st.copy(isInsert = true)
      if (cur.kind != TokKind.TKId) return st.copy(isInsert = true)
      val table = cur.text; i += 1
      if (!acceptKw("values")) return st.copy(isInsert = true, insTable = table)
      if (!accept(TokKind.TKLp)) return st.copy(isInsert = true, insTable = table)
      val vals = ArrayBuffer[Value]()
      while (cur.kind != TokKind.TKRp && cur.kind != TokKind.TKEof) {
        if (cur.kind == TokKind.TKInt) { vals += vInt(cur.text.toLong); i += 1 }
        else if (cur.kind == TokKind.TKString) { vals += vText(cur.text); i += 1 }
        else if (acceptKw("null")) { vals += vNull }
        else return st.copy(isInsert = true, insTable = table, insVals = vals)
        if (!accept(TokKind.TKComma)) { /* break */ }
        if (cur.kind == TokKind.TKRp) { /* break */ }
        if (cur.kind == TokKind.TKRp) { /* break */ }
        // Need to break properly
        if (cur.kind == TokKind.TKRp) { /* done */ }
        if (!accept(TokKind.TKComma)) { /* break */ }
        // Actually let's redo this loop more carefully
        // The C code: after adding value, if (!p_accept(COMMA)) break;
        // Let me restructure
        // We already consumed comma or not above; let's just use a flag
        // Actually the above is messy. Let me rewrite.
        // We'll break out here
        // (This won't work cleanly; let me restructure the whole while)
        // For now, let's just break
        // Actually the issue is the while condition checks RP, so let's just
        // handle comma properly
        // Let me restart this method
        // I'll just return what we have and handle it differently
        // Actually, let me just break
        // The while condition will handle it
        // Let me just do nothing here and let the while re-check
        // But we already consumed comma above... this is getting messy.
        // Let me just break out
        // Actually, the simplest fix: don't consume comma above, just break
        // But we already did. Let me just return.
        return st.copy(isInsert = true, insTable = table, insVals = vals)
      }
      accept(TokKind.TKRp)
      st.copy(isInsert = true, insTable = table, insVals = vals)
    }

    // Let me rewrite parseInsert properly
    def parseInsert2(st: Stmt): Stmt = {
      if (!acceptKw("into")) return st.copy(isInsert = true)
      if (cur.kind != TokKind.TKId) return st.copy(isInsert = true)
      val table = cur.text; i += 1
      if (!acceptKw("values")) return st.copy(isInsert = true, insTable = table)
      if (!accept(TokKind.TKLp)) return st.copy(isInsert = true, insTable = table)
      val vals = ArrayBuffer[Value]()
      var done = false
      while (!done && cur.kind != TokKind.TKRp && cur.kind != TokKind.TKEof) {
        if (cur.kind == TokKind.TKInt) { vals += vInt(cur.text.toLong); i += 1 }
        else if (cur.kind == TokKind.TKString) { vals += vText(cur.text); i += 1 }
        else if (acceptKw("null")) { vals += vNull }
        else { done = true }
        if (!done) {
          if (!accept(TokKind.TKComma)) done = true
        }
      }
      accept(TokKind.TKRp)
      st.copy(isInsert = true, insTable = table, insVals = vals)
    }

    def parseSelect(st: Stmt): Stmt = {
      var selStar = false
      var selCols = ArrayBuffer[ResultCol]()
      if (accept(TokKind.TKStar)) {
        selStar = true
      } else {
        var done = false
        while (!done) {
          val rc = if (accept(TokKind.TKStar)) {
            ResultCol(null, true)
          } else if (cur.kind == TokKind.TKId || cur.kind == TokKind.TKKw) {
            var buf = cur.text; i += 1
            if (cur.kind == TokKind.TKDot) {
              i += 1
              if (accept(TokKind.TKStar)) {
                ResultCol(null, true)
              } else {
                buf += "." + cur.text; i += 1
                ResultCol(buf, false)
              }
            } else {
              ResultCol(buf, false)
            }
          } else return st.copy(isSelect = true)
          selCols += rc
          if (!accept(TokKind.TKComma)) done = true
        }
      }
      if (!acceptKw("from")) return st.copy(isSelect = true, selStar = selStar, selCols = selCols)
      if (cur.kind != TokKind.TKId) return st.copy(isSelect = true, selStar = selStar, selCols = selCols)
      val tables = ArrayBuffer[TableRef]()
      // first table
      var tname = cur.text; i += 1
      var alias: String = null
      if (cur.kind == TokKind.TKId && !peekKw("on") && !peekKw("where") && !peekKw("order") && !peekKw("inner") && !peekKw("join")) {
        alias = cur.text; i += 1
      }
      tables += TableRef(tname, alias)
      // joins
      var joinOn: Expr = null
      while (peekKw("inner") || peekKw("join")) {
        if (acceptKw("inner")) { if (!acceptKw("join")) return st.copy(isSelect = true, selStar = selStar, selCols = selCols, selTables = tables) }
        else acceptKw("join")
        if (cur.kind != TokKind.TKId) return st.copy(isSelect = true, selStar = selStar, selCols = selCols, selTables = tables)
        val jtname = cur.text; i += 1
        var jalias: String = null
        if (cur.kind == TokKind.TKId && !peekKw("on") && !peekKw("where") && !peekKw("order")) {
          jalias = cur.text; i += 1
        }
        tables += TableRef(jtname, jalias)
        if (acceptKw("on")) {
          val on = parseExpr
          if (joinOn == null) joinOn = on
          else joinOn = Expr.EBinop("AND", joinOn, on)
        }
      }
      var where: Expr = null
      if (acceptKw("where")) where = parseExpr
      var orderCol: String = null
      var orderDesc = false
      if (acceptKw("order")) {
        if (!acceptKw("by")) return st.copy(isSelect = true, selStar = selStar, selCols = selCols, selTables = tables, selWhere = where, selJoinOn = joinOn)
        if (cur.kind != TokKind.TKId && cur.kind != TokKind.TKKw) return st.copy(isSelect = true, selStar = selStar, selCols = selCols, selTables = tables, selWhere = where, selJoinOn = joinOn)
        orderCol = cur.text; i += 1
        if (acceptKw("desc")) orderDesc = true
        else acceptKw("asc")
      }
      st.copy(isSelect = true, selStar = selStar, selCols = selCols, selTables = tables,
        selWhere = where, selOrderCol = orderCol, selOrderDesc = orderDesc, selJoinOn = joinOn)
    }

    def parse: Stmt = {
      var st = Stmt()
      if (peekKw("begin")) { st = st.copy(isBegin = true); i += 1; acceptKw("transaction") }
      else if (peekKw("commit")) { st = st.copy(isCommit = true); i += 1; acceptKw("transaction") }
      else if (acceptKw("create")) { if (acceptKw("table")) st = parseCreate(st) else return null }
      else if (acceptKw("insert")) st = parseInsert2(st)
      else if (acceptKw("select")) st = parseSelect(st)
      else return null
      accept(TokKind.TKSemi)
      st
    }
  }

  // ---------- Row context for eval ----------
  case class RowCtx(refs: ArrayBuffer[TableRef], tabs: ArrayBuffer[Table], rows: ArrayBuffer[Row]) {
    def colIndex(col: String): Option[(Int, Int)] = {
      val dot = col.indexOf('.')
      if (dot >= 0) {
        val tname = col.substring(0, dot)
        val cname = col.substring(dot + 1)
        for (i <- refs.indices) {
          val tn = if (refs(i).alias != null) refs(i).alias else refs(i).tname
          if (tn.equalsIgnoreCase(tname)) {
            val ci = Schema.colIndex(tabs(i), cname)
            if (ci >= 0) return Some((i, ci))
          }
        }
        None
      } else {
        for (i <- refs.indices) {
          val ci = Schema.colIndex(tabs(i), col)
          if (ci >= 0) return Some((i, ci))
        }
        None
      }
    }
  }

  def evalExpr(e: Expr, c: RowCtx): Value = {
    if (e == null) return vNull
    e match {
      case Expr.EInt(v) => vInt(v)
      case Expr.EStr(s) => vText(s)
      case Expr.ECol(col) =>
        c.colIndex(col) match {
          case Some((ti, ci)) => c.rows(ti).vals(ci).copy
          case None => vNull
        }
      case Expr.EBinop(op, l, r) =>
        val a = evalExpr(l, c)
        val b = evalExpr(r, c)
        if (op.equalsIgnoreCase("AND")) vInt(if (vTruthy(a) && vTruthy(b)) 1 else 0)
        else if (op.equalsIgnoreCase("OR")) vInt(if (vTruthy(a) || vTruthy(b)) 1 else 0)
        else {
          val cmp = vCmp(a, b)
          val res = op match {
            case "=" => cmp == 0
            case "<>" => cmp != 0
            case "<" => cmp < 0
            case ">" => cmp > 0
            case "<=" => cmp <= 0
            case ">=" => cmp >= 0
            case _ => false
          }
          vInt(if (res) 1 else 0)
        }
    }
  }

  def rowMatch(where: Expr, c: RowCtx): Boolean = {
    if (where == null) return true
    vTruthy(evalExpr(where, c))
  }

  // ---------- Database ----------
  class DB {
    val schema = new Schema()
    val stores = ArrayBuffer[RowStore]()
    var errmsg: String = ""
    var inTxn: Boolean = false

    def execCreate(st: Stmt): Int = {
      if (schema.add(st.ctName, st.ctCols) != 0) {
        errmsg = s"table already exists: ${st.ctName}"
        return -1
      }
      stores += new RowStore()
      0
    }

    def execInsert(st: Stmt): Int = {
      val idx = schema.index(st.insTable)
      if (idx < 0) { errmsg = s"no such table: ${st.insTable}"; return -1 }
      val rs = stores(idx)
      val vals = st.insVals.map(_.copy)
      rs.rows += Row(vals)
      0
    }
  }

  // ---------- Prepared statement ----------
  class StmtHandle(val db: DB, val st: Stmt) {
    var started = false
    var done = false
    var sorted = ArrayBuffer[Row]()
    var curSorted = 0
    var outrow: ArrayBuffer[Value] = ArrayBuffer[Value]()
    var nout = 0

    def collectMatching(): Unit = {
      val n = st.selTables.size
      val idxs = st.selTables.map(t => db.schema.index(t.tname))
      val tabs = st.selTables.map(t => db.schema.find(t.tname).orNull)
      // nested loop
      val curs = idxs.map(idx => if (idx >= 0) db.stores(idx).rows.iterator else Iterator[Row]())
      // We need nested loop; use recursive approach
      def nestedLoop(depth: Int, accRows: ArrayBuffer[Row]): Unit = {
        if (depth == n) {
          val c = RowCtx(st.selTables, tabs, accRows)
          if (rowMatch(st.selWhere, c) && (st.selJoinOn == null || rowMatch(st.selJoinOn, c))) {
            val combined = ArrayBuffer[Value]()
            for (r <- accRows) combined ++= r.vals.map(_.copy)
            sorted += Row(combined)
          }
        } else {
          val storeIdx = idxs(depth)
          if (storeIdx < 0) return
          for (r <- db.stores(storeIdx).rows) {
            accRows += r
            nestedLoop(depth + 1, accRows)
            accRows.remove(accRows.size - 1)
          }
        }
      }
      nestedLoop(0, ArrayBuffer[Row]())

      // ORDER BY
      if (st.selOrderCol != null && st.selTables.size == 1) {
        val tab = tabs(0)
        val cidx = Schema.colIndex(tab, st.selOrderCol)
        if (cidx >= 0) {
          sorted = sorted.sortWith { (ra, rb) =>
            val cmp = vCmp(ra.vals(cidx), rb.vals(cidx))
            if (st.selOrderDesc) cmp > 0 else cmp < 0
          }
        }
      }
    }

    def stepSelect: Int = {
      if (!started) { started = true; collectMatching() }
      if (curSorted >= sorted.size) return 101 // DONE
      val r = sorted(curSorted); curSorted += 1
      val n = st.selTables.size
      val tabs = st.selTables.map(t => db.schema.find(t.tname).orNull)
      val offsets = new Array[Int](n)
      var off = 0
      for (i <- 0 until n) { offsets(i) = off; off += tabs(i).cols.size }
      val ctx = RowCtx(st.selTables, tabs, ArrayBuffer(r))
      outrow = ArrayBuffer[Value]()
      if (st.selStar) {
        for (i <- 0 until n; j <- 0 until tabs(i).cols.size)
          outrow += r.vals(offsets(i) + j).copy
      } else {
        for (rc <- st.selCols) {
          if (rc.star) {
            for (i <- 0 until n; j <- 0 until tabs(i).cols.size)
              outrow += r.vals(offsets(i) + j).copy
          } else {
            val dot = rc.col.indexOf('.')
            var ti = 0; var ci = -1
            if (dot >= 0) {
              val tname = rc.col.substring(0, dot)
              val cname = rc.col.substring(dot + 1)
              for (i <- 0 until n) {
                val tn = if (st.selTables(i).alias != null) st.selTables(i).alias else st.selTables(i).tname
                if (tn.equalsIgnoreCase(tname)) { ci = Schema.colIndex(tabs(i), cname); ti = i; /* break */ }
              }
            } else {
              for (i <- 0 until n) {
                ci = Schema.colIndex(tabs(i), rc.col)
                if (ci >= 0) { ti = i; /* break */ }
              }
            }
            if (ci < 0) outrow += vNull
            else outrow += r.vals(offsets(ti) + ci).copy
          }
        }
      }
      nout = outrow.size
      100 // ROW
    }
  }

  // ---------- Public API ----------
  def open(name: String): DB = new DB()

  def close(db: DB): Int = 0

  def errmsg(db: DB): String = if (db == null) "" else db.errmsg

  type ExecCallback = (Int, Array[String]) => Unit

  def exec(db: DB, sql: String, cb: ExecCallback = null): Int = {
    val toks = lex(sql)
    val p = new Parser(toks)
    var rc = 0
    while (p.cur.kind != TokKind.TKEof && rc == 0) {
      val st = p.parse
      if (st == null) { db.errmsg = "parse error"; rc = 1 }
      else {
        if (st.isBegin) db.inTxn = true
        else if (st.isCommit) db.inTxn = false
        else if (st.isCreate) { rc = db.execCreate(st) }
        else if (st.isInsert) { rc = db.execInsert(st) }
        else if (st.isSelect) {
          val s = new StmtHandle(db, st)
          var r = 0
          while ({ r = s.stepSelect; r == 100 }) {
            val vals = s.outrow.map(vToText).toArray
            if (cb != null) cb(s.nout, vals)
          }
        }
      }
    }
    rc
  }

  def prepare(db: DB, sql: String): StmtHandle = {
    val toks = lex(sql)
    val p = new Parser(toks)
    val st = p.parse
    if (st == null) null else new StmtHandle(db, st)
  }

  def step(s: StmtHandle): Int = {
    if (s.st.isSelect) s.stepSelect
    else 101
  }

  def columnCount(s: StmtHandle): Int = s.nout

  def columnText(s: StmtHandle, i: Int): String = {
    if (i < 0 || i >= s.nout) null else vToText(s.outrow(i))
  }

  def columnInt64(s: StmtHandle, i: Int): Long = {
    if (i < 0 || i >= s.nout) 0
    else s.outrow(i).vtype match { case VType.VInt => s.outrow(i).ival; case _ => 0 }
  }

  def finalizeStmt(s: StmtHandle): Int = 0

  // ---------- Demo ----------
  def printRow(n: Int, vals: Array[String]): Unit = {
    for (i <- 0 until n) print(vals(i) + (if (i + 1 < n) " | " else "\n"))
  }

  def main(args: Array[String]): Unit = {
    val db = open(":memory:")
    val sql =
      "CREATE TABLE users (id INTEGER, name TEXT);" +
      "INSERT INTO users VALUES (1, 'ada');" +
      "INSERT INTO users VALUES (2, 'grace');" +
      "INSERT INTO users VALUES (3, 'linus');" +
      "SELECT * FROM users WHERE id > 1 ORDER BY id DESC;"
    val rc = exec(db, sql, printRow _)
    if (rc != 0) System.err.println(s"err: ${errmsg(db)}")
    close(db)
  }
}
