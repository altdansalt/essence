/* sqlite_core.c -- a compact, in-memory SQLite-style SQL engine.
 *
 * Bounded reference target for the "essence" porting experiment.
 * Implements a recognizable slice of SQLite's architecture:
 *
 *   - Lexer for a SQL subset
 *   - Recursive-descent parser
 *   - Executor (nested-loop joins, WHERE filter, ORDER BY, projections)
 *   - In-memory table store (linked-list "B-tree")
 *   - Public sqlite3_open/exec/prepare/step/finalize/close API surface
 *
 * Supported SQL: CREATE TABLE, INSERT, SELECT (WHERE, projections,
 * SELECT *, simple inner joins, ORDER BY ... [DESC]), BEGIN/COMMIT.
 *
 * Compile: cc -std=c11 -Wall -Wextra -o sqlite_core sqlite_core.c -DSQLITE_CORE_DEMO
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <ctype.h>
#include <stddef.h>

typedef struct sqlite3 sqlite3;
typedef struct sqlite3_stmt sqlite3_stmt;

/* ---------- Value ---------- */
typedef enum { V_NULL, V_INT, V_TEXT } VType;
typedef struct {
    VType type;
    long ival;
    char *sval;      /* owned when type==V_TEXT */
} Value;

static Value v_null(void)         { Value v={V_NULL,0,NULL}; return v; }
static Value v_int(long i)        { Value v={V_INT,i,NULL}; return v; }
static Value v_text(const char *s){ Value v={V_TEXT,0,strdup(s?s:"")}; return v; }
static void  v_free(Value *v)     { if (v->type==V_TEXT) free(v->sval); v->sval=NULL; }
static Value v_copy(const Value *v){
    if (v->type==V_TEXT) return v_text(v->sval);
    return *v;
}
static int v_cmp(const Value *a, const Value *b){
    if (a->type!=b->type) return (int)a->type-(int)b->type;
    if (a->type==V_INT)  return (a->ival<b->ival)?-1:(a->ival>b->ival);
    if (a->type==V_TEXT) return strcmp(a->sval?a->sval:"", b->sval?b->sval:"");
    return 0;
}
static const char *v_to_text(const Value *v, char *buf, size_t n){
    if (v->type==V_INT)  { snprintf(buf,n,"%ld",v->ival); return buf; }
    if (v->type==V_TEXT) return v->sval;
    return "NULL";
}
static int v_truthy(const Value *v){ Value z=v_int(0); return v_cmp(v,&z)!=0; }

/* ---------- Schema ---------- */
typedef struct {
    char *name;
    char **cols;
    int ncols;
} Table;

typedef struct {
    Table *tables;
    int ntables;
} Schema;

static Table *schema_find(Schema *s, const char *name){
    for (int i=0;i<s->ntables;i++) if (!strcasecmp(s->tables[i].name,name)) return &s->tables[i];
    return NULL;
}
static int schema_index(Schema *s, const char *name){
    for (int i=0;i<s->ntables;i++) if (!strcasecmp(s->tables[i].name,name)) return i;
    return -1;
}
static int schema_add(Schema *s, const char *name, char **cols, int ncols){
    if (schema_find(s,name)) return -1;
    s->tables = realloc(s->tables, (s->ntables+1)*sizeof(Table));
    Table *t = &s->tables[s->ntables++];
    t->name = strdup(name); t->cols = cols; t->ncols = ncols;
    return 0;
}
static int table_colindex(Table *t, const char *col){
    for (int i=0;i<t->ncols;i++) if (!strcasecmp(t->cols[i],col)) return i;
    return -1;
}

/* ---------- Row / store ---------- */
typedef struct {
    Value *vals;
    int n;
} Row;

typedef struct RowNode {
    Row row;
    struct RowNode *next;
} RowNode;

typedef struct {
    RowNode *head, *tail;
    int nrows;
} RowStore;

/* ---------- Lexer ---------- */
typedef enum {
    TK_EOF, TK_ID, TK_INT, TK_STRING, TK_KW, TK_PUNCT,
    TK_STAR, TK_COMMA, TK_LP, TK_RP, TK_SEMI, TK_OP, TK_DOT
} TokKind;
typedef struct { TokKind kind; char *text; } Token;

typedef struct {
    const char *src;
    size_t pos;
    Token *toks;
    int ntoks, cap;
} Lexer;

static const char *KEYWORDS[] = {
    "create","table","insert","into","values","select","from","where",
    "order","by","asc","desc","and","or","not","null","begin","commit",
    "inner","join","on","int","integer","text","primary","key","transaction",NULL
};
static int is_kw_n(const char *s, size_t n){
    for (int i=0;KEYWORDS[i];i++){
        size_t kl=strlen(KEYWORDS[i]);
        if (kl==n && !strncasecmp(s,KEYWORDS[i],n)) return 1;
    }
    return 0;
}
static int is_kw(const char *s){
    for (int i=0;KEYWORDS[i];i++) if (!strcasecmp(s,KEYWORDS[i])) return 1;
    return 0;
}

static void lex_push(Lexer *L, TokKind k, const char *s, size_t n){
    if (L->ntoks==L->cap){ L->cap=L->cap?L->cap*2:16; L->toks=realloc(L->toks,L->cap*sizeof(Token)); }
    L->toks[L->ntoks].kind=k; L->toks[L->ntoks].text=strndup(s,n); L->ntoks++;
}
static int lex(Lexer *L, const char *sql){
    L->src=sql; L->pos=0; L->toks=NULL; L->ntoks=0; L->cap=0;
    while (L->src[L->pos]){
        char c=L->src[L->pos];
        if (isspace((unsigned char)c)){ L->pos++; continue; }
        if (c=='-' && L->src[L->pos+1]=='-'){
            while (L->src[L->pos] && L->src[L->pos]!='\n') L->pos++;
            continue;
        }
        if (isalpha((unsigned char)c) || c=='_'){
            size_t st=L->pos;
            while (isalnum((unsigned char)L->src[L->pos]) || L->src[L->pos]=='_') L->pos++;
            size_t len=L->pos-st; lex_push(L, is_kw_n(L->src+st,len)?TK_KW:TK_ID, L->src+st, len);
            continue;
        }
        if (isdigit((unsigned char)c)){
            size_t st=L->pos;
            while (isdigit((unsigned char)L->src[L->pos])) L->pos++;
            lex_push(L, TK_INT, L->src+st, L->pos-st);
            continue;
        }
        if (c=='\''){
            size_t st=++L->pos;
            while (L->src[L->pos] && L->src[L->pos]!='\'') L->pos++;
            lex_push(L, TK_STRING, L->src+st, L->pos-st);
            if (L->src[L->pos]=='\'') L->pos++;
            continue;
        }
        if (c=='"'){
            size_t st=++L->pos;
            while (L->src[L->pos] && L->src[L->pos]!='"') L->pos++;
            lex_push(L, TK_ID, L->src+st, L->pos-st);
            if (L->src[L->pos]=='"') L->pos++;
            continue;
        }
        switch (c){
            case '*': lex_push(L,TK_STAR,&c,1); L->pos++; break;
            case ',': lex_push(L,TK_COMMA,&c,1); L->pos++; break;
            case '(': lex_push(L,TK_LP,&c,1); L->pos++; break;
            case ')': lex_push(L,TK_RP,&c,1); L->pos++; break;
            case ';': lex_push(L,TK_SEMI,&c,1); L->pos++; break;
            case '.': lex_push(L,TK_DOT,&c,1); L->pos++; break;
            default:
                if (strchr("=<>!",c)){
                    size_t st=L->pos;
                    if (L->src[L->pos+1]=='=') L->pos++;
                    if (c=='<' && L->src[L->pos+1]=='>') L->pos++;
                    if (c=='!' && L->src[L->pos+1]=='=') L->pos++;
                    L->pos++;
                    lex_push(L,TK_OP,L->src+st,L->pos-st);
                } else { lex_push(L,TK_PUNCT,&c,1); L->pos++; }
        }
    }
    lex_push(L,TK_EOF,"",0);
    return 0;
}

/* ---------- AST ---------- */
typedef struct Expr Expr;
typedef enum { E_COL, E_INT, E_STR, E_BINOP } ExprKind;
struct Expr {
    ExprKind kind;
    char *col;
    long ival;
    char *sval;
    char op[4];
    Expr *l, *r;
};

typedef struct { char *col; int star; } ResultCol;
typedef struct { char *tname; char *alias; } TableRef;

typedef struct {
    int is_create, is_insert, is_select, is_begin, is_commit;
    char *ct_name; char **ct_cols; int ct_ncols;
    char *ins_table; Value *ins_vals; int ins_nvals;
    ResultCol *sel_cols; int sel_ncols; int sel_star;
    TableRef *sel_tables; int sel_ntables;
    Expr *sel_where;
    char *sel_order_col; int sel_order_desc;
    Expr *sel_join_on;
} Stmt;

static Expr *new_expr(ExprKind k){ Expr *e=calloc(1,sizeof(Expr)); e->kind=k; return e; }
static void free_expr(Expr *e){
    if (!e) return;
    free(e->col); free(e->sval); free_expr(e->l); free_expr(e->r); free(e);
}

/* ---------- Parser ---------- */
typedef struct { Token *t; int i; } Parser;
static int p_accept(Parser *P, TokKind k, const char *text){
    if (P->t[P->i].kind!=k) return 0;
    if (text && strcasecmp(P->t[P->i].text,text)) return 0;
    P->i++; return 1;
}
static int p_accept_kw(Parser *P, const char *kw){ return p_accept(P, TK_KW, kw); }
static int p_peek_kw(Parser *P, const char *kw){
    return P->t[P->i].kind==TK_KW && !strcasecmp(P->t[P->i].text,kw);
}
static Expr *parse_expr(Parser *P);

static Expr *parse_primary(Parser *P){
    Token *t=&P->t[P->i];
    if (t->kind==TK_INT){ Expr *e=new_expr(E_INT); e->ival=atol(t->text); P->i++; return e; }
    if (t->kind==TK_STRING){ Expr *e=new_expr(E_STR); e->sval=strdup(t->text); P->i++; return e; }
    if (t->kind==TK_ID || t->kind==TK_KW){
        Expr *e=new_expr(E_COL);
        char buf[256]; snprintf(buf,sizeof buf,"%s",t->text); P->i++;
        if (P->t[P->i].kind==TK_DOT){
            P->i++;
            snprintf(buf+strlen(buf),sizeof(buf)-strlen(buf),".%s",P->t[P->i].text);
            P->i++;
        }
        e->col=strdup(buf);
        return e;
    }
    if (p_accept(P,TK_LP,NULL)){ Expr *e=parse_expr(P); p_accept(P,TK_RP,NULL); return e; }
    return NULL;
}
static Expr *parse_cmp(Parser *P){
    Expr *l=parse_primary(P);
    if (P->t[P->i].kind==TK_OP){
        Expr *e=new_expr(E_BINOP);
        strncpy(e->op,P->t[P->i].text,3);
        P->i++; e->l=l; e->r=parse_primary(P); return e;
    }
    return l;
}
static Expr *parse_expr(Parser *P){
    Expr *l=parse_cmp(P);
    if (p_peek_kw(P,"and")||p_peek_kw(P,"or")){
        Expr *e=new_expr(E_BINOP);
        strncpy(e->op,p_peek_kw(P,"and")?"AND":"OR",3);
        P->i++; e->l=l; e->r=parse_expr(P); return e;
    }
    return l;
}

static int parse_create(Parser *P, Stmt *st){
    st->is_create=1;
    if (P->t[P->i].kind!=TK_ID && P->t[P->i].kind!=TK_KW) return -1;
    st->ct_name=strdup(P->t[P->i].text); P->i++;
    if (!p_accept(P,TK_LP,NULL)) return -1;
    while (P->t[P->i].kind!=TK_RP && P->t[P->i].kind!=TK_EOF){
        if (P->t[P->i].kind!=TK_ID && P->t[P->i].kind!=TK_KW) return -1;
        st->ct_cols=realloc(st->ct_cols,(st->ct_ncols+1)*sizeof(char*));
        st->ct_cols[st->ct_ncols++]=strdup(P->t[P->i].text);
        P->i++;
        while (P->t[P->i].kind!=TK_COMMA && P->t[P->i].kind!=TK_RP && P->t[P->i].kind!=TK_EOF) P->i++;
        p_accept(P,TK_COMMA,NULL);
    }
    p_accept(P,TK_RP,NULL);
    return 0;
}
static int parse_insert(Parser *P, Stmt *st){
    st->is_insert=1;
    if (!p_accept_kw(P,"into")) return -1;
    if (P->t[P->i].kind!=TK_ID) return -1;
    st->ins_table=strdup(P->t[P->i].text); P->i++;
    if (!p_accept_kw(P,"values")) return -1;
    if (!p_accept(P,TK_LP,NULL)) return -1;
    while (P->t[P->i].kind!=TK_RP && P->t[P->i].kind!=TK_EOF){
        Value v;
        if (P->t[P->i].kind==TK_INT) v=v_int(atol(P->t[P->i].text));
        else if (P->t[P->i].kind==TK_STRING) v=v_text(P->t[P->i].text);
        else if (p_accept_kw(P,"null")) v=v_null();
        else return -1;
        P->i++;
        st->ins_vals=realloc(st->ins_vals,(st->ins_nvals+1)*sizeof(Value));
        st->ins_vals[st->ins_nvals++]=v;
        if (!p_accept(P,TK_COMMA,NULL)) break;
    }
    if (!p_accept(P,TK_RP,NULL)) return -1;
    return 0;
}
static int parse_select(Parser *P, Stmt *st){
    st->is_select=1;
    if (p_accept(P,TK_STAR,NULL)){ st->sel_star=1; }
    else do {
        st->sel_cols=realloc(st->sel_cols,(st->sel_ncols+1)*sizeof(ResultCol));
        ResultCol *rc=&st->sel_cols[st->sel_ncols++]; rc->star=0; rc->col=NULL;
        if (p_accept(P,TK_STAR,NULL)){ rc->star=1; }
        else if (P->t[P->i].kind==TK_ID || P->t[P->i].kind==TK_KW){
            char buf[256]; snprintf(buf,sizeof buf,"%s",P->t[P->i].text); P->i++;
            if (P->t[P->i].kind==TK_DOT){
                P->i++;
                if (p_accept(P,TK_STAR,NULL)) rc->star=1;
                else { snprintf(buf+strlen(buf),sizeof(buf)-strlen(buf),".%s",P->t[P->i].text); P->i++; rc->col=strdup(buf); }
            } else rc->col=strdup(buf);
        } else return -1;
    } while (p_accept(P,TK_COMMA,NULL));
    if (!p_accept_kw(P,"from")) return -1;
    if (P->t[P->i].kind!=TK_ID) return -1;
    /* first table */
    st->sel_tables=realloc(st->sel_tables,(st->sel_ntables+1)*sizeof(TableRef));
    {
        TableRef *tr=&st->sel_tables[st->sel_ntables++]; tr->tname=NULL; tr->alias=NULL;
        tr->tname=strdup(P->t[P->i].text); P->i++;
        if (P->t[P->i].kind==TK_ID && !p_peek_kw(P,"on") && !p_peek_kw(P,"where")
            && !p_peek_kw(P,"order") && !p_peek_kw(P,"inner") && !p_peek_kw(P,"join")){
            tr->alias=strdup(P->t[P->i].text); P->i++;
        }
    }
    /* zero or more: [INNER] JOIN table ON cond  */
    while (p_peek_kw(P,"inner") || p_peek_kw(P,"join")){
        if (p_accept_kw(P,"inner")){ if (!p_accept_kw(P,"join")) return -1; }
        else p_accept_kw(P,"join");
        if (P->t[P->i].kind!=TK_ID) return -1;
        st->sel_tables=realloc(st->sel_tables,(st->sel_ntables+1)*sizeof(TableRef));
        TableRef *tr=&st->sel_tables[st->sel_ntables++]; tr->tname=NULL; tr->alias=NULL;
        tr->tname=strdup(P->t[P->i].text); P->i++;
        if (P->t[P->i].kind==TK_ID && !p_peek_kw(P,"on") && !p_peek_kw(P,"where") && !p_peek_kw(P,"order")){
            tr->alias=strdup(P->t[P->i].text); P->i++;
        }
        if (p_accept_kw(P,"on")){
            Expr *on=parse_expr(P);
            /* AND-combine multiple ON conditions into sel_join_on */
            if (!st->sel_join_on) st->sel_join_on=on;
            else { Expr *and=new_expr(E_BINOP); strcpy(and->op,"AND"); and->l=st->sel_join_on; and->r=on; st->sel_join_on=and; }
        }
    }
    if (p_accept_kw(P,"where")) st->sel_where=parse_expr(P);
    if (p_accept_kw(P,"order")){
        if (!p_accept_kw(P,"by")) return -1;
        if (P->t[P->i].kind!=TK_ID && P->t[P->i].kind!=TK_KW) return -1;
        st->sel_order_col=strdup(P->t[P->i].text); P->i++;
        if (p_accept_kw(P,"desc")) st->sel_order_desc=1;
        else p_accept_kw(P,"asc");
    }
    return 0;
}
static int parse(Parser *P, Stmt *st){
    memset(st,0,sizeof *st);
    if (p_peek_kw(P,"begin")){ st->is_begin=1; P->i++; p_accept_kw(P,"transaction"); }
    else if (p_peek_kw(P,"commit")){ st->is_commit=1; P->i++; p_accept_kw(P,"transaction"); }
    else if (p_accept_kw(P,"create")){ if (p_accept_kw(P,"table")) parse_create(P,st); else return -1; }
    else if (p_accept_kw(P,"insert")) parse_insert(P,st);
    else if (p_accept_kw(P,"select")) parse_select(P,st);
    else return -1;
    p_accept(P,TK_SEMI,NULL);
    return 0;
}

/* ---------- Database ---------- */
struct sqlite3 {
    Schema schema;
    RowStore *stores;
    char errmsg[256];
    int in_txn;
};

static int db_exec_create(sqlite3 *db, Stmt *st){
    if (schema_add(&db->schema, st->ct_name, st->ct_cols, st->ct_ncols)){
        snprintf(db->errmsg,sizeof db->errmsg,"table already exists: %s", st->ct_name);
        return -1;
    }
    st->ct_cols=NULL; st->ct_ncols=0;
    db->stores=realloc(db->stores,db->schema.ntables*sizeof(RowStore));
    memset(&db->stores[db->schema.ntables-1],0,sizeof(RowStore));
    return 0;
}
static int db_exec_insert(sqlite3 *db, Stmt *st){
    int idx=schema_index(&db->schema, st->ins_table);
    if (idx<0){ snprintf(db->errmsg,sizeof db->errmsg,"no such table: %s", st->ins_table); return -1; }
    RowStore *rs=&db->stores[idx];
    RowNode *n=calloc(1,sizeof(RowNode));
    n->row.n=st->ins_nvals;
    n->row.vals=calloc(st->ins_nvals,sizeof(Value));
    for (int i=0;i<st->ins_nvals;i++) n->row.vals[i]=v_copy(&st->ins_vals[i]);
    if (rs->tail) rs->tail->next=n; else rs->head=n;
    rs->tail=n; rs->nrows++;
    return 0;
}

/* ---------- expression eval ---------- */
typedef struct { TableRef *refs; int n; Table **tabs; Row *rows; } RowCtx;
static int rowctx_colindex(RowCtx *c, const char *col, int *tabidx, int *colidx){
    const char *dot=strchr(col,'.');
    if (dot){
        char tname[128]; snprintf(tname,sizeof tname,"%.*s",(int)(dot-col),col);
        const char *cname=dot+1;
        for (int i=0;i<c->n;i++){
            const char *tn = c->refs[i].alias?c->refs[i].alias:c->refs[i].tname;
            if (!strcasecmp(tn,tname)){
                int ci=table_colindex(c->tabs[i],cname);
                if (ci>=0){ *tabidx=i; *colidx=ci; return 0; }
            }
        }
        return -1;
    }
    for (int i=0;i<c->n;i++){
        int ci=table_colindex(c->tabs[i],col);
        if (ci>=0){ *tabidx=i; *colidx=ci; return 0; }
    }
    return -1;
}
static Value eval_expr(Expr *e, RowCtx *c){
    if (!e) return v_null();
    if (e->kind==E_INT) return v_int(e->ival);
    if (e->kind==E_STR) return v_text(e->sval);
    if (e->kind==E_COL){
        int ti,ci; if (rowctx_colindex(c,e->col,&ti,&ci)<0) return v_null();
        return v_copy(&c->rows[ti].vals[ci]);
    }
    if (e->kind==E_BINOP){
        Value a=eval_expr(e->l,c), b=eval_expr(e->r,c);
        Value res=v_null();
        if (!strcasecmp(e->op,"AND")){ res=v_int(v_truthy(&a) && v_truthy(&b)); }
        else if (!strcasecmp(e->op,"OR")){ res=v_int(v_truthy(&a) || v_truthy(&b)); }
        else {
            int cmp=v_cmp(&a,&b);
            if (!strcmp(e->op,"=")) res=v_int(cmp==0);
            else if (!strcmp(e->op,"<>")) res=v_int(cmp!=0);
            else if (!strcmp(e->op,"<")) res=v_int(cmp<0);
            else if (!strcmp(e->op,">")) res=v_int(cmp>0);
            else if (!strcmp(e->op,"<=")) res=v_int(cmp<=0);
            else if (!strcmp(e->op,">=")) res=v_int(cmp>=0);
        }
        v_free(&a); v_free(&b);
        return res;
    }
    return v_null();
}
static int row_match(Expr *where, RowCtx *c){
    if (!where) return 1;
    Value v=eval_expr(where,c);
    int m=v_truthy(&v); v_free(&v); return m;
}

/* ---------- prepared statement (SELECT executor) ---------- */
struct sqlite3_stmt {
    sqlite3 *db;
    Stmt st;
    int *iters;
    RowNode **cur;
    int started;
    int done;
    Value *outrow;
    int nout;
    /* materialized sorted rows for ORDER BY */
    Row *sorted;
    int nsorted, cur_sorted;
};

static void collect_matching(sqlite3_stmt *s, sqlite3 *db){
    int n=s->st.sel_ntables;
    int *idx=calloc(n,sizeof(int));
    Table **tabs=calloc(n,sizeof(Table*));
    for (int i=0;i<n;i++){ idx[i]=schema_index(&db->schema,s->st.sel_tables[i].tname); tabs[i]=&db->schema.tables[idx[i]]; }
    /* nested loop */
    RowNode **cur=calloc(n,sizeof(RowNode*));
    for (int i=0;i<n;i++) cur[i]= idx[i]>=0 ? db->stores[idx[i]].head : NULL;
    while (1){
        int ok=1;
        for (int i=0;i<n;i++) if (!cur[i]){ ok=0; break; }
        if (!ok){ break; }
        RowCtx c={ s->st.sel_tables, n, tabs, NULL };
        Row *rows=calloc(n,sizeof(Row));
        for (int i=0;i<n;i++) rows[i]=cur[i]->row;
        c.rows=rows;
        if (row_match(s->st.sel_where,&c) && (!s->st.sel_join_on || row_match(s->st.sel_join_on,&c))){
            s->sorted=realloc(s->sorted,(s->nsorted+1)*sizeof(Row));
            Row *r=&s->sorted[s->nsorted++];
            r->n=0; r->vals=NULL;
            for (int i=0;i<n;i++){
                r->vals=realloc(r->vals,(r->n+rows[i].n)*sizeof(Value));
                for (int j=0;j<rows[i].n;j++) r->vals[r->n++]=v_copy(&rows[i].vals[j]);
            }
        }
        free(rows);
        /* advance innermost */
        int k;
        for (k=n-1;k>=0;k--){
            cur[k]=cur[k]->next;
            if (cur[k]) break;
            if (k>0) cur[k]= idx[k]>=0 ? db->stores[idx[k]].head : NULL;
            else { /* all done */ }
        }
        if (k<0) break;
    }
    free(cur); free(idx); free(tabs);
    /* ORDER BY: simple insertion sort on the named column across all tables */
    if (s->st.sel_order_col){
        int ti,ci; RowCtx tmp={ s->st.sel_tables, s->st.sel_ntables, NULL, NULL };
        Table **tabs2=calloc(s->st.sel_ntables,sizeof(Table*));
        for (int i=0;i<s->st.sel_ntables;i++) tabs2[i]=schema_find(&db->schema,s->st.sel_tables[i].tname);
        tmp.tabs=tabs2;
        /* order col offset within each combined row is ambiguous for joins;
           for single-table we map directly. */
        for (int i=1;i<s->nsorted;i++){
            for (int j=i;j>0;j--){
                /* find the order col by scanning tabs for the single-table case */
                Value *a=NULL,*b=NULL;
                if (s->st.sel_ntables==1){
                    int cidx=table_colindex(tabs2[0], s->st.sel_order_col);
                    if (cidx>=0 && cidx<s->sorted[j-1].n && cidx<s->sorted[j].n){
                        a=&s->sorted[j-1].vals[cidx]; b=&s->sorted[j].vals[cidx];
                    }
                }
                if (!a){ free(tabs2); goto no_sort; }
                int cmp=v_cmp(a,b);
                if ((s->st.sel_order_desc && cmp<0) || (!s->st.sel_order_desc && cmp>0)){
                    Row t=s->sorted[j-1]; s->sorted[j-1]=s->sorted[j]; s->sorted[j]=t;
                } else break;
            }
        }
        free(tabs2);
    }
no_sort:;
}

static int stmt_step_select(sqlite3_stmt *s){
    if (!s->started){
        s->started=1;
        collect_matching(s, s->db);
    }
    if (s->cur_sorted >= s->nsorted) return 101; /* DONE */
    Row *r=&s->sorted[s->cur_sorted++];
    int n=s->st.sel_ntables;
    Table **tabs=calloc(n,sizeof(Table*));
    for (int i=0;i<n;i++) tabs[i]=schema_find(&s->db->schema,s->st.sel_tables[i].tname);
    /* build output row */
    RowCtx c={ s->st.sel_tables, n, tabs, r };
    /* For projections we need per-table column offsets; the combined row r
       is table0.cols ++ table1.cols ++ ... so recompute offsets. */
    int offsets[16];
    int off=0;
    for (int i=0;i<n;i++){ offsets[i]=off; off+=tabs[i]->ncols; }
    /* helper to resolve a "col" or "alias.col" to an index in r */
    int nout = s->st.sel_star ? off : 0;
    if (s->st.sel_star){ for (int i=0;i<n;i++) nout+=tabs[i]->ncols; }
    else for (int k=0;k<s->st.sel_ncols;k++) if (s->st.sel_cols[k].star){ for (int i=0;i<n;i++) nout+=tabs[i]->ncols; } else nout++;
    s->outrow=realloc(s->outrow,nout*sizeof(Value));
    s->nout=0;
    if (s->st.sel_star){
        for (int i=0;i<n;i++) for (int j=0;j<tabs[i]->ncols;j++) s->outrow[s->nout++]=v_copy(&r->vals[offsets[i]+j]);
    } else {
        for (int k=0;k<s->st.sel_ncols;k++){
            ResultCol *rc=&s->st.sel_cols[k];
            if (rc->star){ for (int i=0;i<n;i++) for (int j=0;j<tabs[i]->ncols;j++) s->outrow[s->nout++]=v_copy(&r->vals[offsets[i]+j]); }
            else {
                const char *dot=strchr(rc->col,'.');
                int ti=0,ci=-1;
                if (dot){
                    char tname[128]; snprintf(tname,sizeof tname,"%.*s",(int)(dot-rc->col),rc->col);
                    for (int i=0;i<n;i++){ const char *tn=s->st.sel_tables[i].alias?s->st.sel_tables[i].alias:s->st.sel_tables[i].tname; if(!strcasecmp(tn,tname)){ ci=table_colindex(tabs[i],dot+1); ti=i; break; } }
                } else {
                    for (int i=0;i<n;i++){ ci=table_colindex(tabs[i],rc->col); if(ci>=0){ ti=i; break; } }
                }
                if (ci<0) s->outrow[s->nout++]=v_null();
                else s->outrow[s->nout++]=v_copy(&r->vals[offsets[ti]+ci]);
            }
        }
    }
    free(tabs);
    return 100; /* ROW */
}

/* ---------- public API ---------- */
int sqlite3_open(const char *name, sqlite3 **pp){
    (void)name;
    sqlite3 *db=calloc(1,sizeof(*db));
    *pp=db; return 0;
}
int sqlite3_close(sqlite3 *db){
    if (!db) return 0;
    for (int i=0;i<db->schema.ntables;i++){
        free(db->schema.tables[i].name);
        for (int j=0;j<db->schema.tables[i].ncols;j++) free(db->schema.tables[i].cols[j]);
        free(db->schema.tables[i].cols);
        RowNode *no=db->stores[i].head;
        while (no){ RowNode *nx=no->next; for (int j=0;j<no->row.n;j++) v_free(&no->row.vals[j]); free(no->row.vals); free(no); no=nx; }
    }
    free(db->schema.tables); free(db->stores); free(db);
    return 0;
}
const char *sqlite3_errmsg(sqlite3 *db){ return db?db->errmsg:""; }

static void free_stmt(Stmt *st){
    free(st->ct_name); free(st->ins_table);
    for (int i=0;i<st->ins_nvals;i++) v_free(&st->ins_vals[i]); free(st->ins_vals);
    for (int i=0;i<st->sel_ncols;i++) free(st->sel_cols[i].col); free(st->sel_cols);
    for (int i=0;i<st->sel_ntables;i++){ free(st->sel_tables[i].tname); free(st->sel_tables[i].alias); } free(st->sel_tables);
    free_expr(st->sel_where); free(st->sel_order_col); free_expr(st->sel_join_on);
}

int sqlite3_exec(sqlite3 *db, const char *sql, void (*cb)(void*,int,char**,char**), void *arg, char **err){
    Lexer L; lex(&L,sql);
    Parser P={ L.toks, 0 };
    int rc=0;
    while (P.t[P.i].kind!=TK_EOF){
        Stmt st;
        if (parse(&P,&st)<0){ if(err)*err=strdup("parse error"); rc=1; break; }
        if (st.is_begin){ db->in_txn=1; }
        else if (st.is_commit){ db->in_txn=0; }
        else if (st.is_create){ rc=db_exec_create(db,&st); }
        else if (st.is_insert){ rc=db_exec_insert(db,&st); }
        else if (st.is_select){
            sqlite3_stmt *s=calloc(1,sizeof(*s)); s->db=db; s->st=st;
            int r;
            while ((r=stmt_step_select(s))==100){
                char **vals=calloc(s->nout,sizeof(char*));
                char buf[64];
                for (int i=0;i<s->nout;i++){ const char*t=v_to_text(&s->outrow[i],buf,sizeof buf); vals[i]=(char*)t; }
                if (cb) cb(arg,s->nout,vals,NULL);
                for (int i=0;i<s->nout;i++) v_free(&s->outrow[i]);
                free(vals);
            }
            for (int i=0;i<s->nsorted;i++){ for(int j=0;j<s->sorted[i].n;j++) v_free(&s->sorted[i].vals[j]); free(s->sorted[i].vals); }
            free(s->sorted); free(s->outrow); free(s);
            (void)arg;
        }
        free_stmt(&st);
    }
    if (rc && err && !*err) *err=strdup(db->errmsg);
    for (int i=0;i<L.ntoks;i++) free(L.toks[i].text); free(L.toks);
    return rc;
}

int sqlite3_prepare_v2(sqlite3 *db, const char *sql, int n, sqlite3_stmt **pp, const char **tail){
    char *buf = n<0 ? strdup(sql) : strndup(sql,n);
    Lexer L; lex(&L,buf);
    Parser P={ L.toks,0 };
    Stmt st; if (parse(&P,&st)<0){ for(int i=0;i<L.ntoks;i++)free(L.toks[i].text); free(L.toks); free(buf); return 1; }
    sqlite3_stmt *s=calloc(1,sizeof(*s)); s->db=db; s->st=st;
    *pp=s; (void)tail;
    for (int i=0;i<L.ntoks;i++) free(L.toks[i].text); free(L.toks);
    free(buf);
    return 0;
}
int sqlite3_step(sqlite3_stmt *s){
    if (s->st.is_select) return stmt_step_select(s);
    return 101;
}
int sqlite3_column_count(sqlite3_stmt *s){ return s->nout; }
const char *sqlite3_column_text(sqlite3_stmt *s, int i){
    static __thread char buf[64];
    if (i<0||i>=s->nout) return NULL;
    return v_to_text(&s->outrow[i],buf,sizeof buf);
}
long sqlite3_column_int64(sqlite3_stmt *s,int i){
    if (i<0||i>=s->nout) return 0;
    return s->outrow[i].type==V_INT ? s->outrow[i].ival : 0;
}
int sqlite3_finalize(sqlite3_stmt *s){
    if(!s) return 0;
    free_stmt(&s->st);
    for (int i=0;i<s->nsorted;i++){ for(int j=0;j<s->sorted[i].n;j++) v_free(&s->sorted[i].vals[j]); free(s->sorted[i].vals); }
    free(s->sorted); free(s->outrow); free(s);
    return 0;
}

/* ---------- demo main ---------- */
static void print_row(void *arg, int n, char **vals, char **cols){
    (void)arg;(void)cols;
    for (int i=0;i<n;i++) printf("%s%s", vals[i], i+1<n?" | ":"\n");
}
#ifdef SQLITE_CORE_DEMO
int main(void){
    sqlite3 *db; sqlite3_open(":memory:",&db);
    char *err=NULL;
    const char *sql =
        "CREATE TABLE users (id INTEGER, name TEXT);"
        "INSERT INTO users VALUES (1, 'ada');"
        "INSERT INTO users VALUES (2, 'grace');"
        "INSERT INTO users VALUES (3, 'linus');"
        "SELECT * FROM users WHERE id > 1 ORDER BY id DESC;";
    if (sqlite3_exec(db, sql, print_row, NULL, &err)){ fprintf(stderr,"err: %s\n", err?err:"?"); free(err); }
    sqlite3_close(db);
    return 0;
}
#endif
