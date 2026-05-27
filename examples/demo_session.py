"""
pg2text 사용 예시 — 프로그래밍 방식으로 세션 사용하기

실행 방법:
    python examples/demo_session.py

환경변수:
    ANTHROPIC_API_KEY, PG_HOST, PG_DATABASE, PG_USER, PG_PASSWORD
"""

from pathlib import Path
from pg2text.config import settings
from pg2text.conversation import InteractiveSession
from pg2text.database import DatabaseClient
from pg2text.doc_builder import DocumentBuilder
from pg2text.nl_processor import NLProcessor


def run_demo():
    print("=== postgresql2Text 데모 ===\n")

    # 컴포넌트 초기화
    db = DatabaseClient()
    nlp = NLProcessor()
    doc_builder = DocumentBuilder()

    session = InteractiveSession(
        db_client=db,
        nl_processor=nlp,
        doc_builder=doc_builder,
        history_window=10,
        history_file=Path("./output/demo_history.jsonl"),
    )

    # 세션 시작 (DB 연결 + 스키마 로딩)
    print("DB 연결 중...")
    if not session.start():
        print("DB 연결 실패. .env 파일을 확인하세요.")
        return

    print(f"로딩된 테이블: {', '.join(session.tables)}\n")

    # ── 예시 1: 데이터 조회 및 문서 생성 ──────────────────────────────────────
    print(">>> 질문: 전체 주문 현황 요약 보고서 작성해줘")
    response = session.process("전체 주문 현황 요약 보고서 작성해줘")

    if response.action == "query":
        print(f"✓ 문서 생성: {response.document.title}")
        print(f"  SQL: {response.sql}")
        print(f"  데이터: {response.query_result.row_count}건\n")
    elif response.action == "error":
        print(f"오류: {response.message}\n")

    # ── 예시 2: 문서 편집 ────────────────────────────────────────────────────
    if session.current_document:
        print(">>> 편집: 요약 섹션을 더 간략하게 수정해줘")
        edit_response = session.process("요약 섹션을 더 간략하게 수정해줘")

        if edit_response.action == "edit":
            print(f"✓ 수정 완료: {edit_response.document.title}\n")

    # ── 예시 3: 저장 ─────────────────────────────────────────────────────────
    if session.current_document:
        print(">>> 내보내기: Markdown과 Word 파일 모두 저장")
        paths = session.export_all()
        for fmt, path in paths.items():
            print(f"  [{fmt.upper()}] → {path}")

    db.close()
    print("\n=== 데모 완료 ===")


# ── 직접 API 사용 예시 ────────────────────────────────────────────────────────


def run_api_example():
    """컴포넌트를 직접 사용하는 예시"""
    from pg2text.database import DatabaseClient
    from pg2text.nl_processor import NLProcessor

    db = DatabaseClient()
    nlp = NLProcessor()

    # 스키마 로딩
    db.load_schemas()

    # 1. NL → SQL
    sql_result = nlp.generate_sql(
        user_query="고객별 총 주문 금액을 내림차순으로 보여줘",
        schema=db.schemas,
    )
    print(f"생성된 SQL:\n{sql_result.sql}\n")
    print(f"설명: {sql_result.explanation}\n")

    # 2. SQL 실행
    query_result = db.execute(sql_result.sql)
    print(f"결과:\n{query_result.to_markdown_table()}\n")

    # 3. 문서 생성
    document = nlp.generate_document(
        user_request="고객별 주문 현황 분석",
        query_results=[query_result],
    )
    print(f"문서 제목: {document.title}")
    print(f"내용 미리보기:\n{document.markdown_content[:500]}...\n")

    # 4. 저장
    doc_builder = DocumentBuilder()
    md_path = doc_builder.save(document, format="md")
    print(f"저장 완료: {md_path}")

    db.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "api":
        run_api_example()
    else:
        run_demo()
