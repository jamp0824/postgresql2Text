"""
데이터베이스 모듈 테스트
"""

import pytest
from unittest.mock import MagicMock, patch

from pg2text.database import (
    ColumnInfo,
    TableSchema,
    QueryResult,
    DatabaseClient,
)


# ─── ColumnInfo 테스트 ────────────────────────────────────────────────────────


class TestColumnInfo:
    def test_to_prompt_str_nullable(self):
        col = ColumnInfo(name="email", type="VARCHAR(255)", nullable=True)
        result = col.to_prompt_str()
        assert "email" in result
        assert "VARCHAR(255)" in result
        assert "NULL 가능" in result

    def test_to_prompt_str_not_null(self):
        col = ColumnInfo(name="id", type="INTEGER", nullable=False)
        result = col.to_prompt_str()
        assert "NOT NULL" in result

    def test_to_prompt_str_with_comment(self):
        col = ColumnInfo(name="status", type="TEXT", nullable=True, comment="주문 상태")
        result = col.to_prompt_str()
        assert "주문 상태" in result


# ─── TableSchema 테스트 ───────────────────────────────────────────────────────


class TestTableSchema:
    def _make_schema(self) -> TableSchema:
        return TableSchema(
            schema="public",
            name="orders",
            columns=[
                ColumnInfo("order_id", "INTEGER", False),
                ColumnInfo("customer_id", "INTEGER", False),
                ColumnInfo("amount", "NUMERIC(10,2)", True),
            ],
            primary_keys=["order_id"],
            foreign_keys=[
                {
                    "constrained_columns": ["customer_id"],
                    "referred_table": "customers",
                    "referred_columns": ["id"],
                }
            ],
        )

    def test_full_name(self):
        schema = self._make_schema()
        assert schema.full_name == "public.orders"

    def test_to_prompt_str_contains_table(self):
        schema = self._make_schema()
        prompt = schema.to_prompt_str()
        assert "public.orders" in prompt
        assert "order_id" in prompt
        assert "[PK]" in prompt

    def test_to_prompt_str_contains_fk(self):
        schema = self._make_schema()
        prompt = schema.to_prompt_str()
        assert "customers" in prompt


# ─── QueryResult 테스트 ───────────────────────────────────────────────────────


class TestQueryResult:
    def _make_result(self) -> QueryResult:
        return QueryResult(
            sql="SELECT * FROM orders",
            columns=["id", "amount", "status"],
            rows=[(1, 100.0, "paid"), (2, 200.0, "pending")],
            row_count=2,
        )

    def test_is_success(self):
        result = self._make_result()
        assert result.is_success is True

    def test_is_failure(self):
        result = QueryResult(sql="", columns=[], rows=[], row_count=0, error="오류")
        assert result.is_success is False

    def test_to_markdown_table(self):
        result = self._make_result()
        md = result.to_markdown_table()
        assert "| id |" in md
        assert "| 1 |" in md
        assert "---" in md

    def test_to_markdown_table_empty(self):
        result = QueryResult(sql="", columns=[], rows=[], row_count=0)
        md = result.to_markdown_table()
        assert "결과 없음" in md

    def test_to_dict_list(self):
        result = self._make_result()
        dicts = result.to_dict_list()
        assert len(dicts) == 2
        assert dicts[0] == {"id": 1, "amount": 100.0, "status": "paid"}

    def test_to_markdown_table_max_rows(self):
        result = QueryResult(
            sql="SELECT 1",
            columns=["n"],
            rows=[(i,) for i in range(100)],
            row_count=100,
        )
        md = result.to_markdown_table(max_rows=10)
        assert "100건" in md
        assert "10건" in md


# ─── DatabaseClient 테스트 ───────────────────────────────────────────────────


class TestDatabaseClientSecurity:
    """SELECT-only 보안 정책 테스트"""

    @patch("pg2text.database.create_engine")
    def test_reject_insert(self, mock_engine):
        mock_engine.return_value = MagicMock()
        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("INSERT INTO users VALUES (1, 'hack')")
        assert not result.is_success
        assert "SELECT" in result.error

    @patch("pg2text.database.create_engine")
    def test_reject_drop(self, mock_engine):
        mock_engine.return_value = MagicMock()
        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("DROP TABLE users")
        assert not result.is_success

    @patch("pg2text.database.create_engine")
    def test_reject_update(self, mock_engine):
        mock_engine.return_value = MagicMock()
        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("UPDATE users SET name='hack'")
        assert not result.is_success

    @patch("pg2text.database.create_engine")
    def test_allow_select(self, mock_engine):
        """SELECT는 엔진 레벨에서 진행 (모킹된 연결)"""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.keys.return_value = ["id", "name"]
        mock_result.fetchall.return_value = [(1, "Alice")]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        mock_engine.return_value.connect.return_value = mock_conn

        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("SELECT id, name FROM users")
        assert result.is_success
        assert result.columns == ["id", "name"]

    @patch("pg2text.database.create_engine")
    def test_allow_with_cte(self, mock_engine):
        """WITH(CTE) 쿼리도 허용"""
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.keys.return_value = ["count"]
        mock_result.fetchall.return_value = [(42,)]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        mock_engine.return_value.connect.return_value = mock_conn

        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("WITH cte AS (SELECT 42) SELECT count FROM cte")
        assert result.is_success


    @patch("pg2text.database.create_engine")
    def test_reject_multistatement(self, mock_engine):
        mock_engine.return_value = MagicMock()
        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("SELECT 1; SELECT 2")
        assert not result.is_success
        assert "다중문" in result.error

    @patch("pg2text.database.create_engine")
    def test_reject_cte_with_insert(self, mock_engine):
        mock_engine.return_value = MagicMock()
        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute(
            "WITH injected AS (INSERT INTO users(id) VALUES (1) RETURNING id) SELECT * FROM injected"
        )
        assert not result.is_success
        assert "SELECT / WITH" in result.error or "쓰기/DDL" in result.error

    @patch("pg2text.database.create_engine")
    def test_allow_select_with_comment(self, mock_engine):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.keys.return_value = ["n"]
        mock_result.fetchall.return_value = [(1,)]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        mock_engine.return_value.connect.return_value = mock_conn

        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("-- read only\nSELECT 1 AS n")
        assert result.is_success

    @patch("pg2text.database.create_engine")
    def test_allow_function_call_in_select(self, mock_engine):
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.keys.return_value = ["now"]
        mock_result.fetchall.return_value = [("2026-01-01",)]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.execute.return_value = mock_result
        mock_engine.return_value.connect.return_value = mock_conn

        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("SELECT now()")
        assert result.is_success

    @patch("pg2text.database.create_engine")
    def test_reject_call_command(self, mock_engine):
        mock_engine.return_value = MagicMock()
        client = DatabaseClient(database_url="postgresql://test")
        result = client.execute("CALL refresh_materialized_views()")
        assert not result.is_success
