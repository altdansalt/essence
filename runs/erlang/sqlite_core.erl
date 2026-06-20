project(Cols, Star, TableRefs, TableData, Offsets, Row) ->
    case Star of
        true ->
            %% SELECT * - output all columns from all tables
            Row;
        false ->
            %% Specific columns
            lists:flatmap(
                fun(Col) ->
                    case Col of
                        star ->
                            %% table.* - output all columns from all tables
                            Row;
                        {star_table, _TName} ->
                            %% Same as star in C implementation
                            Row;
                        {col, Name} ->
                            case find_col(TableRefs, TableData, Offsets, Name) of
                                not_found -> [null];
                                Idx -> [lists:nth(Idx + 1, Row)]
                            end
                    end
                end, Cols)
    end.
