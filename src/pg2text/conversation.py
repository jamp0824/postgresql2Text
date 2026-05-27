"""
대화 세션 관리 모듈 — 멀티턴 대화 상태 및 작업 오케스트레이션
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pg2text.config import settings
from pg2text.database import DatabaseClient, QueryResult
from pg2text.doc_builder import DocumentBuilder
from pg2text.nl_processor import GeneratedDocument, NLProcessor

logger = logging.getLogger(__name__)

# ─── 데이터 클래스 ────────────────────────────────────────────────────────────

MessageRole = Literal["user", "assistant"]


@dataclass
class Message:
    """대화 메시지"""
    role: MessageRole
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_api_dict(self) -> dict:
        """Anthropic API 형식으로 변환"""
        return {"role": self.role, "content": self.content}


@dataclass
class SessionResponse:
    """세션 처리 결과"""
    action: Literal["query", "edit", "export", "info", "error"]
    message: str
    document: GeneratedDocument | None = None
    query_result: QueryResult | None = None
    sql: str | None = None
    exported_paths: dict[str, Path] = field(default_factory=dict)


# ─── 대화 기록 ────────────────────────────────────────────────────────────────


class ConversationHistory:
    """
    슬라이딩 윈도우 방식의 대화 기록 관리.
    최근 N개 메시지만 유지해 컨텍스트 초과 방지.
    """

    def __init__(self, window: int = 20):
        self._messages: deque[Message] = deque(maxlen=window)

    def add(self, role: MessageRole, content: str, **metadata) -> None:
        self._messages.append(
            Message(role=role, content=content, metadata=metadata)
        )

    def to_api_messages(self) -> list[dict]:
        """Anthropic API 메시지 형식으로 변환"""
        return [m.to_api_dict() for m in self._messages]

    def save(self, path: Path) -> None:
        """JSON Lines 형식으로 저장"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for msg in self._messages:
                f.write(
                    json.dumps(
                        {
                            "role": msg.role,
                            "content": msg.content,
                            "timestamp": msg.timestamp.isoformat(),
                            "metadata": msg.metadata,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    @classmethod
    def load(cls, path: Path, window: int = 20) -> "ConversationHistory":
        """저장된 기록 불러오기"""
        history = cls(window=window)
        if not path.exists():
            return history
        with open(path, encoding="utf-8") as f:
            for line in f:
                data = json.loads(line.strip())
                history.add(data["role"], data["content"], **data.get("metadata", {}))
        return history

    def clear(self) -> None:
        self._messages.clear()

    def __len__(self) -> int:
        return len(self._messages)


# ─── 인텐트 분류기 ────────────────────────────────────────────────────────────

# 문서 편집 키워드 패턴
_EDIT_PATTERNS = re.compile(
    r"^(수정|변경|바꿔|고쳐|추가|삭제|제거|더\s*자세|간략|짧게|길게|다시\s*써|"
    r"edit|modify|change|update|rewrite|add|remove|make\s+it|shorter|longer|"
    r"더\s*써|요약해|정리해)",
    re.IGNORECASE,
)

# 내보내기 키워드 패턴 (문장 어디에든 있을 수 있으므로 ^ 미사용)
_EXPORT_PATTERNS = re.compile(
    r"(저장|내보내|export|save|파일로|워드로|워드\s*파일|docx|markdown|md\s*파일)",
    re.IGNORECASE,
)

# 새 데이터 조회 키워드 패턴
_QUERY_PATTERNS = re.compile(
    r"(보여줘|조회|검색|찾아줘|알려줘|얼마나|몇\s*개|목록|리스트|분석|"
    r"show|select|find|list|count|how many|what|which|when|where|"
    r"보고서|리포트|report|현황|통계|집계)",
    re.IGNORECASE,
)


def classify_intent(
    user_input: str,
    has_current_document: bool,
) -> Literal["query", "edit", "export", "info"]:
    """
    사용자 입력의 의도를 분류.

    Args:
        user_input: 사용자 입력 텍스트
        has_current_document: 현재 문서가 있는지 여부
    Returns:
        "query" | "edit" | "export" | "info"
    """
    stripped = user_input.strip()

    # 내보내기
    if _EXPORT_PATTERNS.search(stripped):
        return "export"

    # 편집 (현재 문서가 있을 때만)
    if has_current_document and _EDIT_PATTERNS.match(stripped):
        return "edit"

    # 조회
    if _QUERY_PATTERNS.search(stripped):
        return "query"

    # 현재 문서가 있고 짧은 지시형 문장이면 편집으로 처리
    if has_current_document and len(stripped) < 100 and not "?" in stripped:
        # 동사로 시작하는 짧은 문장
        if re.match(r"^[가-힣a-zA-Z]+", stripped):
            return "edit"

    return "info"


# ─── 인터랙티브 세션 ──────────────────────────────────────────────────────────


class InteractiveSession:
    """
    메인 대화 세션 오케스트레이터.

    컴포넌트:
    - DatabaseClient: DB 연결 및 쿼리 실행
    - NLProcessor: Claude API 기반 NL→SQL 및 문서 생성
    - DocumentBuilder: 문서 파일 저장
    - ConversationHistory: 대화 기록 관리
    """

    def __init__(
        self,
        db_client: DatabaseClient,
        nl_processor: NLProcessor,
        doc_builder: DocumentBuilder,
        history_window: int = 20,
        history_file: Path | None = None,
    ):
        self._db = db_client
        self._nlp = nl_processor
        self._doc_builder = doc_builder
        self._history = ConversationHistory(window=history_window)
        self._history_file = history_file
        self._current_document: GeneratedDocument | None = None
        self._schema_loaded = False

        # 기존 기록 로드
        if history_file and history_file.exists():
            self._history = ConversationHistory.load(history_file, window=history_window)
            logger.info("대화 기록 불러옴: %s (%d개)", history_file, len(self._history))

    # ── 초기화 ───────────────────────────────────────────

    def start(self) -> bool:
        """
        세션 시작 — DB 연결 테스트 및 스키마 로딩.
        Returns: 성공 여부
        """
        if not self._db.test_connection():
            return False

        self._db.load_schemas()
        self._schema_loaded = True
        logger.info("세션 시작 완료 (테이블 %d개)", len(self._db.list_tables()))
        return True

    # ── 사용자 입력 처리 ─────────────────────────────────

    def process(self, user_input: str) -> SessionResponse:
        """
        사용자 입력을 처리하고 적절한 액션 수행.

        Args:
            user_input: 사용자가 입력한 텍스트
        Returns:
            SessionResponse
        """
        if not self._schema_loaded:
            return SessionResponse(
                action="error",
                message="DB가 연결되지 않았습니다. 먼저 세션을 시작하세요.",
            )

        intent = classify_intent(user_input, has_current_document=self._current_document is not None)
        logger.debug("인텐트 분류: %s → %s", user_input[:50], intent)

        if intent == "query":
            return self._handle_query(user_input)
        elif intent == "edit":
            return self._handle_edit(user_input)
        elif intent == "export":
            return self._handle_export(user_input)
        else:
            return self._handle_info(user_input)

    def _handle_query(self, user_input: str) -> SessionResponse:
        """새 데이터 조회 및 문서 생성"""
        history_msgs = self._history.to_api_messages()

        # 1. NL → SQL
        sql_result = self._nlp.generate_sql(
            user_query=user_input,
            schema=self._db.schemas,
            conversation_history=history_msgs,
        )

        if not sql_result.is_success:
            self._history.add("user", user_input)
            self._history.add("assistant", f"SQL 생성 실패: {sql_result.error}")
            return SessionResponse(
                action="error",
                message=f"SQL 생성에 실패했습니다: {sql_result.error}",
            )

        # 2. SQL 실행
        query_result = self._db.execute(sql_result.sql)

        if not query_result.is_success:
            # SQL 오류 → 재시도 프롬프트 포함
            error_msg = (
                f"SQL 실행 오류: {query_result.error}\n"
                f"실행된 SQL: {sql_result.sql}"
            )
            self._history.add("user", user_input)
            self._history.add("assistant", error_msg)
            return SessionResponse(
                action="error",
                message=error_msg,
                sql=sql_result.sql,
                query_result=query_result,
            )

        # 3. 데이터 → 문서 생성
        # 이전 SQL 생성 히스토리를 업데이트하고 문서 생성
        doc_history = history_msgs + [
            {"role": "user", "content": user_input},
            {
                "role": "assistant",
                "content": f"SQL 생성 완료:\n```sql\n{sql_result.sql}\n```\n{sql_result.explanation}",
            },
        ]

        document = self._nlp.generate_document(
            user_request=user_input,
            query_results=[query_result],
            conversation_history=doc_history,
        )

        self._current_document = document

        # 대화 기록 업데이트
        self._history.add("user", user_input)
        self._history.add(
            "assistant",
            f"문서 생성 완료: {document.title}\n(행: {query_result.row_count}건)",
            sql=sql_result.sql,
            doc_title=document.title,
        )

        self._save_history()

        return SessionResponse(
            action="query",
            message=f"'{document.title}' 문서가 생성되었습니다. ({query_result.row_count}건)",
            document=document,
            query_result=query_result,
            sql=sql_result.sql,
        )

    def _handle_edit(self, user_input: str) -> SessionResponse:
        """기존 문서 편집"""
        if not self._current_document:
            return SessionResponse(
                action="error",
                message="편집할 문서가 없습니다. 먼저 데이터를 조회해 문서를 만들어주세요.",
            )

        history_msgs = self._history.to_api_messages()

        # 추가 데이터가 필요한지 확인 (키워드 기반 간단 판단)
        additional_data = None
        if any(kw in user_input for kw in ["추가", "더", "함께", "포함", "넣어"]):
            # 추가 데이터 조회 시도
            sql_result = self._nlp.generate_sql(
                user_query=f"편집 요청에서 추가로 필요한 데이터: {user_input}",
                schema=self._db.schemas,
                conversation_history=history_msgs,
            )
            if sql_result.is_success and sql_result.sql:
                extra_result = self._db.execute(sql_result.sql)
                if extra_result.is_success and extra_result.row_count > 0:
                    additional_data = [extra_result]

        updated_doc = self._nlp.edit_document(
            current_document=self._current_document,
            edit_request=user_input,
            additional_data=additional_data,
            conversation_history=history_msgs,
        )

        self._current_document = updated_doc

        # 대화 기록 업데이트
        self._history.add("user", user_input)
        self._history.add(
            "assistant",
            f"문서 수정 완료: {updated_doc.title}",
            action="edit",
        )

        self._save_history()

        return SessionResponse(
            action="edit",
            message=f"문서가 수정되었습니다: '{updated_doc.title}'",
            document=updated_doc,
        )

    def _handle_export(self, user_input: str) -> SessionResponse:
        """문서 내보내기"""
        if not self._current_document:
            return SessionResponse(
                action="error",
                message="내보낼 문서가 없습니다.",
            )

        # 포맷 판단
        lower = user_input.lower()
        if "docx" in lower or "word" in lower or "워드" in lower:
            formats = ["docx"]
        elif "md" in lower or "markdown" in lower or "마크다운" in lower:
            formats = ["md"]
        else:
            formats = ["md", "docx"]  # 기본: 둘 다

        exported: dict[str, Path] = {}
        for fmt in formats:
            path = self._doc_builder.save(self._current_document, format=fmt)
            exported[fmt] = path

        paths_str = ", ".join(str(p) for p in exported.values())
        return SessionResponse(
            action="export",
            message=f"문서 저장 완료: {paths_str}",
            document=self._current_document,
            exported_paths=exported,
        )

    def _handle_info(self, user_input: str) -> SessionResponse:
        """일반 정보 요청 처리"""
        context = ""
        if self._current_document:
            context = f"현재 문서: {self._current_document.title}"
        if self._db.schemas:
            context += f"\n사용 가능한 테이블: {', '.join(self._db.list_tables())}"

        history_msgs = self._history.to_api_messages()
        response_text = self._nlp.chat(
            user_message=user_input,
            conversation_history=history_msgs,
            context=context if context else None,
        )

        self._history.add("user", user_input)
        self._history.add("assistant", response_text)
        self._save_history()

        return SessionResponse(
            action="info",
            message=response_text,
            document=self._current_document,
        )

    # ── 유틸리티 ─────────────────────────────────────────

    def _save_history(self) -> None:
        """대화 기록 파일에 저장"""
        if self._history_file:
            self._history.save(self._history_file)

    def export_current(self, format: str = "md", output_path: Path | None = None) -> Path | None:
        """현재 문서를 직접 내보내기"""
        if not self._current_document:
            return None
        return self._doc_builder.save(self._current_document, format=format, output_path=output_path)

    def export_all(self) -> dict[str, Path]:
        """현재 문서를 모든 형식으로 내보내기"""
        if not self._current_document:
            return {}
        return self._doc_builder.save_all(self._current_document)

    @property
    def current_document(self) -> GeneratedDocument | None:
        return self._current_document

    @property
    def tables(self) -> list[str]:
        return self._db.list_tables()

    @property
    def schema_prompt(self) -> str:
        return self._db.schema_prompt()
