"""
데이터베이스 모듈 — PostgreSQL 연결, 스키마 로딩, 쿼리 실행
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from pg2text.config import settings
from pg2text.sql_guard import validate_readonly_sql

logger = logging.getLogger(__name__)


# ─── 데이터 클래스 ────────────────────────────────────────────────────────────


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    comment: str | None = None

    def to_prompt_str(self) -> str:
        null_str = "NULL 가능" if self.nullable else "NOT NULL"
        comment_str = f" -- {self.comment}" if self.comment else ""
        return f"  {self.name} {self.type} ({null_str}){comment_str}"


@dataclass
class TableSchema:
    schema: str
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=list)
    foreign_keys: list[dict] = field(default_factory=list)
    comment: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"

    def to_prompt_str(self) -> str:
        """LLM 프롬프트에 삽입할 스키마 텍스트"""
        lines = [f"테이블: {self.full_name}"]
        if self.comment:
            lines.append(f"  설명: {self.comment}")
        lines.append("  컬럼:")
        for col in self.columns:
            pk_mark = " [PK]" if col.name in self.primary_keys else ""
            lines.append(col.to_prompt_str() + pk_mark)
        if self.foreign_keys:
            lines.append("  외래키:")
            for fk in self.foreign_keys:
                lines.append(
                    f"    {fk['constrained_columns']} → "
                    f"{fk['referred_table']}.{fk['referred_columns']}"
                )
        return "\n".join(lines)


@dataclass
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[tuple]
    row_count: int
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None

    def to_markdown_table(self, max_rows: int = 50) -> str:
        """Markdown 테이블로 변환"""
        if not self.columns:
            return "_결과 없음_"
        header = "| " + " | ".join(self.columns) + " |"
        separator = "| " + " | ".join(["---"] * len(self.columns)) + " |"
        rows_to_show = self.rows[:max_rows]
        data_rows = []
        for row in rows_to_show:
            cells = " | ".join(str(v) if v is not None else "NULL" for v in row)
            data_rows.append(f"| {cells} |")
        parts = [header, separator] + data_rows
        if self.row_count > max_rows:
            parts.append(f"\n_(전체 {self.row_count}건 중 {max_rows}건 표시)_")
        return "\n".join(parts)

    def to_dict_list(self) -> list[dict[str, Any]]:
        """딕셔너리 리스트로 변환"""
        return [dict(zip(self.columns, row)) for row in self.rows]


# ─── 데이터베이스 클라이언트 ──────────────────────────────────────────────────


class DatabaseClient:
    """PostgreSQL 연결 및 스키마/쿼리 관리"""

    def __init__(self, database_url: str | None = None):
        url = database_url or settings.database_url
        self._engine: Engine = create_engine(url, pool_pre_ping=True)
        self._schemas: dict[str, TableSchema] = {}

    # ── 연결 확인 ───────────────────────────────────────
    def test_connection(self) -> bool:
        """연결 성공 여부 반환"""
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError as e:
            logger.error("DB 연결 실패: %s", e)
            return False

    # ── 스키마 로딩 ─────────────────────────────────────
    def load_schemas(
        self,
        schemas: list[str] | None = None,
        include_tables: list[str] | None = None,
        exclude_tables: list[str] | None = None,
    ) -> dict[str, TableSchema]:
        """
        데이터베이스 스키마 정보 로딩.

        Args:
            schemas: 대상 스키마 목록 (None이면 public만)
            include_tables: 포함할 테이블 패턴
            exclude_tables: 제외할 테이블 패턴
        """
        inspector = inspect(self._engine)
        target_schemas = schemas or ["public"]
        loaded: dict[str, TableSchema] = {}

        for schema_name in target_schemas:
            table_names = inspector.get_table_names(schema=schema_name)
            for table_name in table_names:
                full_name = f"{schema_name}.{table_name}"
                if include_tables and table_name not in include_tables:
                    continue
                if exclude_tables and table_name in exclude_tables:
                    continue

                columns_raw = inspector.get_columns(table_name, schema=schema_name)
                pk_info = inspector.get_pk_constraint(table_name, schema=schema_name)
                fks = inspector.get_foreign_keys(table_name, schema=schema_name)
                table_comment = inspector.get_table_comment(table_name, schema=schema_name)

                columns = [
                    ColumnInfo(
                        name=col["name"],
                        type=str(col["type"]),
                        nullable=col.get("nullable", True),
                        comment=col.get("comment"),
                    )
                    for col in columns_raw
                ]

                loaded[full_name] = TableSchema(
                    schema=schema_name,
                    name=table_name,
                    columns=columns,
                    primary_keys=pk_info.get("constrained_columns", []),
                    foreign_keys=fks,
                    comment=table_comment.get("text") if table_comment else None,
                )

        self._schemas = loaded
        logger.info("스키마 로딩 완료: %d개 테이블", len(loaded))
        return loaded

    @property
    def schemas(self) -> dict[str, TableSchema]:
        return self._schemas

    def schema_prompt(self) -> str:
        """LLM에 전달할 스키마 컨텍스트 문자열"""
        if not self._schemas:
            return "스키마 정보 없음"
        parts = ["=== 데이터베이스 스키마 ==="]
        for tbl in self._schemas.values():
            parts.append(tbl.to_prompt_str())
        return "\n\n".join(parts)

    # ── 쿼리 실행 ───────────────────────────────────────
    def execute(self, sql: str, params: dict | None = None) -> QueryResult:
        """
        SELECT 쿼리 실행 후 QueryResult 반환.
        안전을 위해 SELECT만 허용 (DML 차단).
        """
        validation_error = validate_readonly_sql(sql)
        if validation_error:
            return QueryResult(
                sql=sql,
                columns=[],
                rows=[],
                row_count=0,
                error=validation_error,
            )

        try:
            with self._engine.connect() as conn:
                result = conn.execute(text(sql), params or {})
                columns = list(result.keys())
                rows = result.fetchall()
                return QueryResult(
                    sql=sql,
                    columns=columns,
                    rows=[tuple(r) for r in rows],
                    row_count=len(rows),
                )
        except SQLAlchemyError as e:
            logger.error("쿼리 실행 오류: %s\nSQL: %s", e, sql)
            return QueryResult(sql=sql, columns=[], rows=[], row_count=0, error=str(e))

    def list_tables(self) -> list[str]:
        """로딩된 테이블 목록"""
        return list(self._schemas.keys())

    def close(self):
        self._engine.dispose()
