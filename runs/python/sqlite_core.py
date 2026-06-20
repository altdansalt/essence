while (P.t[P.i].kind!=TK_EOF){
    Stmt st;
    if (parse(&P,&st)<0){ ...; rc=1; break; }
    ...
}
