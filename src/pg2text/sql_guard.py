"""SQL 실행 전 안전성 검사 유틸."""

from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import ParseError

BLOCKED_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Drop,
    exp.Alter,
    exp.Truncate,
    exp.Command,  # CALL/DO/COPY 등 command 계열 차단
)


def _contains_blocked_nodes(expression: exp.Expression) -> bool:
    return any(isinstance(node, BLOCKED_NODES) for node in expression.walk())


def _is_select_only(expression: exp.Expression) -> bool:
    """루트/CTE가 SELECT 계열인지 확인."""
    if isinstance(expression, exp.Subquery):
        return _is_select_only(expression.unnest())

    if isinstance(expression, exp.Union):
        return _is_select_only(expression.left) and _is_select_only(expression.right)

    if isinstance(expression, exp.Select):
        with_clause = expression.args.get("with")
        if isinstance(with_clause, exp.With):
            for cte in with_clause.expressions:
                cte_query = cte.this
                if cte_query is None or not _is_select_only(cte_query):
                    return False
        return True

    return False


def validate_readonly_sql(sql: str) -> str | None:
    """읽기 전용 SQL인지 검사하고, 실패 시 에러 메시지를 반환."""
    try:
        statements = parse(sql, read="postgres")
    except ParseError as e:
        return f"SQL 파싱 실패: {e}"

    if not statements:
        return "SQL 문이 비어 있습니다."

    if len(statements) > 1:
        return "보안상 세미콜론(;) 다중문은 허용되지 않습니다."

    statement = statements[0]

    if statement is None or not _is_select_only(statement):
        return "보안상 SELECT / WITH 쿼리만 허용됩니다."

    if _contains_blocked_nodes(statement):
        return (
            "보안상 쓰기/DDL/명령 구문(INSERT, UPDATE, DELETE, MERGE, DROP, "
            "ALTER, TRUNCATE, CALL, DO, COPY)은 허용되지 않습니다."
        )

    return None
