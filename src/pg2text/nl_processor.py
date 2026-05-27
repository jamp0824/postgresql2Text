"""
자연어 처리 모듈 — Gemini API를 사용해 NL→SQL 변환 및 문서 내용 생성
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from pg2text.config import settings
from pg2text.database import QueryResult, TableSchema

logger = logging.getLogger(__name__)

# ─── 시스템 프롬프트 ──────────────────────────────────────────────────────────

_SQL_SYSTEM_PROMPT = """당신은 PostgreSQL 전문가입니다.
사용자의 자연어 요청을 받아 올바른 SQL SELECT 쿼리를 생성합니다.

규칙:
1. 오직 SELECT 또는 WITH(CTE) 쿼리만 생성합니다. INSERT/UPDATE/DELETE/DROP 등 절대 금지.
2. 존재하는 테이블과 컬럼만 사용합니다 (스키마 참고).
3. 한국어 컬럼명/테이블명이 있으면 큰따옴표로 감쌉니다: "컬럼명"
4. LIMIT를 적절히 설정해 과도한 결과를 방지합니다 (기본 100).
5. 응답은 반드시 JSON 형식으로만 반환합니다:
   {"sql": "SELECT ...", "explanation": "쿼리 설명"}
6. SQL에 대한 설명은 explanation 필드에 한국어로 작성합니다.
7. 모호한 요청이면 가장 합리적으로 해석해서 쿼리를 작성합니다."""

_DOC_SYSTEM_PROMPT = """당신은 전문 문서 작성가입니다.
데이터베이스 조회 결과를 바탕으로 체계적이고 읽기 쉬운 문서를 Markdown 형식으로 작성합니다.

문서 구조 원칙:
1. 제목 (# 레벨): 문서의 핵심 주제
2. 요약 (## 요약): 2-3문장의 핵심 내용
3. 주요 데이터 (## 데이터 분석): 표와 수치를 활용한 상세 분석
4. 인사이트 (## 핵심 인사이트): 데이터에서 도출된 의미 있는 패턴/트렌드
5. 결론 및 제언 (## 결론): 실행 가능한 제안

규칙:
- 수치는 구체적으로 언급 (예: "약 30%" 아닌 "정확히 28.5%")
- 표는 Markdown 형식으로 작성
- 전문적이지만 이해하기 쉬운 언어 사용
- 데이터가 없는 섹션은 생략
- 응답은 순수 Markdown만 (JSON 래퍼 없이)"""

_EDIT_SYSTEM_PROMPT = """당신은 전문 문서 편집자입니다.
기존 Markdown 문서를 사용자의 요청에 따라 수정합니다.

편집 원칙:
1. 사용자가 명시적으로 변경을 요청한 부분만 수정합니다
2. 나머지 문서 내용은 그대로 보존합니다
3. 추가 데이터가 제공되면 해당 데이터를 문서에 통합합니다
4. 문서 형식(Markdown)을 유지합니다
5. 응답은 수정된 전체 Markdown 문서만 반환합니다 (설명 없이)"""


# ─── 데이터 클래스 ────────────────────────────────────────────────────────────


@dataclass
class SQLGenResult:
    """SQL 생성 결과"""
    sql: str
    explanation: str
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None


@dataclass
class DocumentSection:
    """문서 섹션"""
    title: str
    content: str
    level: int = 2  # Markdown 헤딩 레벨


@dataclass
class GeneratedDocument:
    """생성된 문서"""
    title: str
    markdown_content: str
    query_results: list[QueryResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── NL 프로세서 ──────────────────────────────────────────────────────────────


class NLProcessor:
    """
    자연어 처리기.
    - 자연어 → SQL 변환
    - 데이터 → 문서 내용 생성
    - 문서 대화형 수정
    """

    def __init__(self, model: str | None = None):
        self._client: genai.Client | None = None
        self._model = model or settings.pg2text_model

    @property
    def client(self) -> genai.Client:
        """Gemini 클라이언트를 지연 생성합니다."""
        if self._client is None:
            api_key = settings.gemini_api_key or settings.google_api_key
            if not api_key:
                raise RuntimeError(
                    "GEMINI_API_KEY가 설정되지 않았습니다. .env 파일에 Gemini API 키를 입력하세요."
                )
            self._client = genai.Client(api_key=api_key)
        return self._client

    def _to_gemini_contents(
        self,
        messages: list[dict] | None,
        user_message: str,
    ) -> list[types.Content]:
        """내부 대화 기록을 Gemini Content 형식으로 변환합니다."""
        contents: list[types.Content] = []
        for message in messages or []:
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            role = "model" if message.get("role") == "assistant" else "user"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content)],
                )
            )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
        )
        return contents

    def _generate_text(
        self,
        *,
        system_prompt: str,
        user_message: str,
        conversation_history: list[dict] | None = None,
        max_tokens: int = 2048,
        response_mime_type: str | None = None,
    ) -> str:
        """Gemini generate_content 호출을 공통 처리합니다."""
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "max_output_tokens": max_tokens,
        }
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type

        response = self.client.models.generate_content(
            model=self._model,
            contents=self._to_gemini_contents(conversation_history, user_message),
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = (response.text or "").strip()
        if not text:
            raise RuntimeError("Gemini API가 빈 응답을 반환했습니다.")
        return text

    # ── NL → SQL ────────────────────────────────────────

    def generate_sql(
        self,
        user_query: str,
        schema: dict[str, TableSchema],
        conversation_history: list[dict] | None = None,
    ) -> SQLGenResult:
        """
        자연어 질문을 PostgreSQL SELECT 쿼리로 변환.

        Args:
            user_query: 사용자의 자연어 질문
            schema: 데이터베이스 스키마 정보
            conversation_history: 이전 대화 기록 (멀티턴 지원)
        """
        schema_text = "\n\n".join(t.to_prompt_str() for t in schema.values())
        # 스키마를 사용자 메시지에 포함
        user_message = f"""다음 스키마를 참고하여 SQL 쿼리를 작성해주세요.

{schema_text}

사용자 요청: {user_query}"""

        messages.append({"role": "user", "content": user_message})

        try:
            raw_text = self._generate_text(
                system_prompt=_SQL_SYSTEM_PROMPT,
                user_message=user_message,
                conversation_history=conversation_history,
                max_tokens=2048,
                response_mime_type="application/json",
            )

            # JSON 추출 (마크다운 코드블록 처리)
            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if not json_match:
                return SQLGenResult(
                    sql="",
                    explanation="",
                    error=f"JSON 파싱 실패: {raw_text[:200]}",
                )

            parsed = json.loads(json_match.group())
            return SQLGenResult(
                sql=parsed.get("sql", "").strip(),
                explanation=parsed.get("explanation", ""),
            )

        except json.JSONDecodeError as e:
            return SQLGenResult(sql="", explanation="", error=f"JSON 파싱 오류: {e}")
        except Exception as e:
            logger.error("Gemini API 오류: %s", e)
            return SQLGenResult(sql="", explanation="", error=f"API 오류: {e}")

    # ── 데이터 → 문서 ────────────────────────────────────

    def generate_document(
        self,
        user_request: str,
        query_results: list[QueryResult],
        conversation_history: list[dict] | None = None,
    ) -> GeneratedDocument:
        """
        조회 결과를 바탕으로 문서 생성.

        Args:
            user_request: 원본 사용자 요청
            query_results: 실행된 쿼리 결과 목록
            conversation_history: 이전 대화 기록
        """
        # 데이터 컨텍스트 구성
        data_context_parts = []
        for i, result in enumerate(query_results, 1):
            if not result.is_success:
                data_context_parts.append(f"### 쿼리 {i} 오류\n{result.error}")
                continue
            data_context_parts.append(
                f"### 쿼리 {i} 결과 ({result.row_count}건)\n"
                f"SQL: `{result.sql}`\n\n"
                f"{result.to_markdown_table(max_rows=30)}"
            )

        data_context = "\n\n".join(data_context_parts)
        user_message = f"""다음 데이터를 바탕으로 문서를 작성해주세요.

사용자 요청: {user_request}

=== 데이터 ===
{data_context}

위 데이터를 분석하여 전문적인 Markdown 문서를 작성해주세요."""

        messages.append({"role": "user", "content": user_message})

        try:
            markdown_content = self._generate_text(
                system_prompt=_DOC_SYSTEM_PROMPT,
                user_message=user_message,
                conversation_history=conversation_history,
                max_tokens=4096,
            )

            # 제목 추출
            title_match = re.search(r"^#\s+(.+)$", markdown_content, re.MULTILINE)
            title = title_match.group(1) if title_match else "데이터 분석 보고서"

            return GeneratedDocument(
                title=title,
                markdown_content=markdown_content,
                query_results=query_results,
                metadata={"user_request": user_request},
            )

        except Exception as e:
            logger.error("문서 생성 API 오류: %s", e)
            return GeneratedDocument(
                title="오류",
                markdown_content=f"# 오류\n\n문서 생성 중 오류가 발생했습니다: {e}",
                query_results=query_results,
            )

    # ── 문서 편집 (대화형) ──────────────────────────────

    def edit_document(
        self,
        current_document: GeneratedDocument,
        edit_request: str,
        additional_data: list[QueryResult] | None = None,
        conversation_history: list[dict] | None = None,
    ) -> GeneratedDocument:
        """
        기존 문서를 사용자 요청에 따라 수정.

        Args:
            current_document: 현재 문서
            edit_request: 편집 요청 (자연어)
            additional_data: 추가로 조회된 데이터 (있는 경우)
            conversation_history: 이전 대화 기록
        """
        add_data_text = ""
        if additional_data:
            parts = []
            for result in additional_data:
                if result.is_success:
                    parts.append(
                        f"추가 데이터 ({result.row_count}건):\n"
                        f"{result.to_markdown_table(max_rows=20)}"
                    )
            add_data_text = "\n\n".join(parts)

        user_message = f"""현재 문서를 다음과 같이 수정해주세요.

수정 요청: {edit_request}

=== 현재 문서 ===
{current_document.markdown_content}
"""
        if add_data_text:
            user_message += f"\n=== 추가 데이터 ===\n{add_data_text}"

        try:
            new_markdown = self._generate_text(
                system_prompt=_EDIT_SYSTEM_PROMPT,
                user_message=user_message,
                conversation_history=conversation_history,
                max_tokens=4096,
            )

            # 제목 추출
            title_match = re.search(r"^#\s+(.+)$", new_markdown, re.MULTILINE)
            title = title_match.group(1) if title_match else current_document.title

            updated_results = current_document.query_results[:]
            if additional_data:
                updated_results.extend(additional_data)

            return GeneratedDocument(
                title=title,
                markdown_content=new_markdown,
                query_results=updated_results,
                metadata={**current_document.metadata, "last_edit": edit_request},
            )

        except Exception as e:
            logger.error("문서 편집 API 오류: %s", e)
            return current_document  # 실패 시 원본 반환

    # ── 자유 대화 (도움말 등) ────────────────────────────

    def chat(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        context: str | None = None,
    ) -> str:
        """일반 대화 응답 생성"""
        system = (
            "당신은 PostgreSQL 데이터 분석 전문가이자 문서 작성 도우미입니다. "
            "사용자가 데이터를 이해하고 문서를 작성하는 것을 도와주세요."
        )
        if context:
            system += f"\n\n현재 컨텍스트:\n{context}"

        try:
            return self._generate_text(
                system_prompt=system,
                user_message=user_message,
                conversation_history=conversation_history,
                max_tokens=1024,
            )
        except Exception as e:
            return f"오류: {e}"
