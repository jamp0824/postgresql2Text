"""
CLI 진입점 — Typer 기반 명령줄 인터페이스
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich import print as rprint
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

console = Console()
app = typer.Typer(
    name="pg2text",
    help="🗄️  PostgreSQL 데이터를 자연어로 조회하고 문서로 작성합니다",
    add_completion=False,
    pretty_exceptions_show_locals=False,
)


# ─── 로깅 설정 ────────────────────────────────────────────────────────────────


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


# ─── 헬퍼 함수 ───────────────────────────────────────────────────────────────


def _print_banner():
    console.print(
        Panel.fit(
            "[bold cyan]postgresql2Text[/bold cyan]\n"
            "[dim]PostgreSQL 데이터를 자연어로 조회하고 대화형으로 문서를 작성합니다[/dim]",
            border_style="cyan",
        )
    )


def _print_sql(sql: str) -> None:
    console.print(Panel(Syntax(sql, "sql", theme="monokai"), title="생성된 SQL", border_style="yellow"))


def _print_result_table(columns: list[str], rows: list[tuple], max_rows: int = 20) -> None:
    table = Table(show_header=True, header_style="bold magenta")
    for col in columns:
        table.add_column(col, overflow="fold")
    for row in rows[:max_rows]:
        table.add_row(*[str(v) if v is not None else "NULL" for v in row])
    console.print(table)
    if len(rows) > max_rows:
        console.print(f"[dim]... (전체 {len(rows)}건 중 {max_rows}건 표시)[/dim]")


def _print_schema_summary(tables: list[str]) -> None:
    console.print(f"[green]✓[/green] 로딩된 테이블: [bold]{len(tables)}개[/bold]")
    for t in tables:
        console.print(f"  [dim]•[/dim] {t}")


# ─── 명령어: connect ──────────────────────────────────────────────────────────


@app.command("connect")
def cmd_connect(
    host: str = typer.Option(None, "--host", "-h", envvar="PG_HOST", help="DB 호스트"),
    port: int = typer.Option(None, "--port", "-p", envvar="PG_PORT", help="DB 포트"),
    database: str = typer.Option(None, "--db", "-d", envvar="PG_DATABASE", help="데이터베이스명"),
    user: str = typer.Option(None, "--user", "-U", envvar="PG_USER", help="사용자명"),
    password: str = typer.Option(None, "--password", "-W", envvar="PG_PASSWORD", help="비밀번호"),
    schema: list[str] = typer.Option(["public"], "--schema", "-s", help="대상 스키마"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="자세한 스키마 출력"),
):
    """데이터베이스 연결을 테스트하고 스키마를 출력합니다."""
    from pg2text.config import settings
    from pg2text.database import DatabaseClient

    setup_logging()
    _print_banner()

    # 설정 오버라이드
    if host:
        settings.pg_host = host
    if port:
        settings.pg_port = port
    if database:
        settings.pg_database = database
    if user:
        settings.pg_user = user
    if password:
        settings.pg_password = password

    console.print(f"\n연결 시도: [cyan]{settings.pg_host}:{settings.pg_port}/{settings.pg_database}[/cyan]")

    db = DatabaseClient()
    with console.status("DB 연결 중..."):
        if not db.test_connection():
            console.print("[red]✗ 연결 실패[/red]")
            raise typer.Exit(1)

        tables = db.load_schemas(schemas=list(schema))

    console.print(f"[green]✓ 연결 성공![/green]")
    _print_schema_summary(db.list_tables())

    if verbose:
        console.print("\n[bold]상세 스키마:[/bold]")
        console.print(db.schema_prompt())

    db.close()


# ─── 명령어: query ────────────────────────────────────────────────────────────


@app.command("query")
def cmd_query(
    question: str = typer.Argument(..., help="자연어로 데이터를 설명하세요"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="출력 파일 경로"),
    format: str = typer.Option("md", "--format", "-f", help="출력 형식: md | docx | all"),
    schema: list[str] = typer.Option(["public"], "--schema", "-s", help="대상 스키마"),
    show_sql: bool = typer.Option(True, "--show-sql/--no-sql", help="생성된 SQL 표시"),
    show_data: bool = typer.Option(True, "--show-data/--no-data", help="조회 결과 표시"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="사용할 Gemini 모델"),
):
    """
    자연어 질문으로 데이터를 조회하고 문서를 생성합니다.

    예시:
        pg2text query "최근 30일간 가장 많이 판매된 상품 TOP 10을 보고서로 작성해줘"
    """
    from pg2text.config import settings
    from pg2text.database import DatabaseClient
    from pg2text.doc_builder import DocumentBuilder
    from pg2text.nl_processor import NLProcessor

    if model:
        settings.pg2text_model = model

    setup_logging()
    _print_banner()
    console.print(f"\n[bold]질문:[/bold] {question}\n")

    db = DatabaseClient()
    nlp = NLProcessor()
    doc_builder = DocumentBuilder()

    try:
        # DB 연결 및 스키마 로딩
        with console.status("DB 연결 및 스키마 로딩..."):
            if not db.test_connection():
                console.print("[red]DB 연결 실패[/red]")
                raise typer.Exit(1)
            db.load_schemas(schemas=list(schema))

        console.print(f"[green]✓[/green] 테이블 {len(db.list_tables())}개 로딩 완료\n")

        # NL → SQL
        with console.status("[yellow]SQL 생성 중...[/yellow]"):
            sql_result = nlp.generate_sql(
                user_query=question,
                schema=db.schemas,
            )

        if not sql_result.is_success:
            console.print(f"[red]SQL 생성 실패:[/red] {sql_result.error}")
            raise typer.Exit(1)

        if show_sql:
            _print_sql(sql_result.sql)
            if sql_result.explanation:
                console.print(f"[dim]{sql_result.explanation}[/dim]\n")

        # 쿼리 실행
        with console.status("[yellow]데이터 조회 중...[/yellow]"):
            query_result = db.execute(sql_result.sql)

        if not query_result.is_success:
            console.print(f"[red]쿼리 오류:[/red] {query_result.error}")
            raise typer.Exit(1)

        console.print(f"[green]✓[/green] {query_result.row_count}건 조회됨\n")

        if show_data and query_result.columns:
            _print_result_table(query_result.columns, query_result.rows)
            console.print()

        # 문서 생성
        with console.status("[yellow]문서 작성 중...[/yellow]"):
            document = nlp.generate_document(
                user_request=question,
                query_results=[query_result],
            )

        console.print(Panel(Markdown(document.markdown_content[:3000]), title=f"📄 {document.title}"))

        # 저장
        if format.lower() == "all":
            paths = doc_builder.save_all(document, output.parent if output else None)
            for fmt, path in paths.items():
                console.print(f"[green]✓[/green] 저장: [cyan]{path}[/cyan] ({fmt})")
        else:
            path = doc_builder.save(document, format=format, output_path=output)
            console.print(f"\n[green]✓[/green] 저장 완료: [cyan]{path}[/cyan]")

    finally:
        db.close()


# ─── 명령어: chat ─────────────────────────────────────────────────────────────


@app.command("chat")
def cmd_chat(
    schema: list[str] = typer.Option(["public"], "--schema", "-s", help="대상 스키마"),
    history_file: Optional[Path] = typer.Option(None, "--history", help="대화 기록 파일"),
    output_dir: Optional[Path] = typer.Option(None, "--output-dir", help="문서 저장 디렉터리"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="사용할 Gemini 모델"),
):
    """
    대화형 세션을 시작합니다.
    데이터 조회, 문서 작성, 문서 편집을 자연어로 수행합니다.

    사용법:
        - 데이터 조회: "지난달 매출 현황 보여줘"
        - 문서 편집: "요약을 더 짧게 수정해줘"
        - 저장: "md 파일로 저장해줘" / "저장"
        - 종료: "exit" / "quit" / Ctrl+C
    """
    from pg2text.config import settings
    from pg2text.conversation import InteractiveSession
    from pg2text.database import DatabaseClient
    from pg2text.doc_builder import DocumentBuilder
    from pg2text.nl_processor import NLProcessor

    if model:
        settings.pg2text_model = model
    if output_dir:
        settings.pg2text_output_dir = output_dir

    setup_logging()
    _print_banner()

    db = DatabaseClient()
    nlp = NLProcessor()
    doc_builder = DocumentBuilder()

    session = InteractiveSession(
        db_client=db,
        nl_processor=nlp,
        doc_builder=doc_builder,
        history_file=history_file,
    )

    # 세션 시작
    with console.status("DB 연결 및 초기화..."):
        if not session.start():
            console.print("[red]DB 연결 실패. .env 파일을 확인하세요.[/red]")
            raise typer.Exit(1)

    console.print(f"\n[green]✓[/green] 연결됨! 테이블 {len(session.tables)}개")
    _print_schema_summary(session.tables)

    # 사용법 안내
    console.print(
        Panel(
            "[bold]사용 방법[/bold]\n"
            "• 데이터 조회: [cyan]\"지난달 매출 TOP 10 보고서 작성해줘\"[/cyan]\n"
            "• 문서 편집: [cyan]\"요약을 더 간결하게 수정해줘\"[/cyan]\n"
            "• 문서 저장: [cyan]\"저장해줘\"[/cyan] / [cyan]\"워드 파일로 저장\"[/cyan]\n"
            "• 도움말: [cyan]\"테이블 목록 알려줘\"[/cyan]\n"
            "• 종료: [cyan]exit[/cyan] 또는 Ctrl+C",
            title="💡 도움말",
            border_style="dim",
        )
    )
    console.print()

    # 대화 루프
    try:
        while True:
            try:
                user_input = Prompt.ask("\n[bold cyan]>[/bold cyan]").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue

            if user_input.lower() in ("exit", "quit", "종료", "그만", "bye"):
                break

            # 입력 처리
            with console.status("처리 중..."):
                response = session.process(user_input)

            # 결과 표시
            if response.action == "error":
                console.print(f"\n[red]오류:[/red] {response.message}")

            elif response.action == "query":
                # SQL 표시
                if response.sql:
                    _print_sql(response.sql)
                # 조회 결과
                if response.query_result and response.query_result.columns:
                    console.print(
                        f"\n[dim]조회 결과 ({response.query_result.row_count}건):[/dim]"
                    )
                    _print_result_table(
                        response.query_result.columns,
                        response.query_result.rows,
                    )
                # 문서 미리보기
                if response.document:
                    console.print()
                    # 처음 1500자만 표시
                    preview = response.document.markdown_content[:1500]
                    if len(response.document.markdown_content) > 1500:
                        preview += "\n\n...(이하 생략)..."
                    console.print(
                        Panel(
                            Markdown(preview),
                            title=f"📄 {response.document.title}",
                            border_style="green",
                        )
                    )
                console.print(f"\n[green]✓[/green] {response.message}")

            elif response.action == "edit":
                if response.document:
                    preview = response.document.markdown_content[:1500]
                    if len(response.document.markdown_content) > 1500:
                        preview += "\n\n...(이하 생략)..."
                    console.print(
                        Panel(
                            Markdown(preview),
                            title=f"✏️ {response.document.title} (수정됨)",
                            border_style="blue",
                        )
                    )
                console.print(f"\n[blue]✓[/blue] {response.message}")

            elif response.action == "export":
                for fmt, path in response.exported_paths.items():
                    console.print(f"[green]✓[/green] [{fmt.upper()}] → [cyan]{path}[/cyan]")

            elif response.action == "info":
                console.print(Panel(Markdown(response.message), border_style="dim"))

    except KeyboardInterrupt:
        pass

    finally:
        db.close()
        if session.current_document:
            console.print(
                f"\n[dim]💾 세션 종료. "
                f"저장되지 않은 문서: '{session.current_document.title}'[/dim]"
            )
            save_on_exit = Prompt.ask(
                "종료 전에 저장하시겠습니까?",
                choices=["md", "docx", "all", "no"],
                default="no",
            )
            if save_on_exit != "no":
                fmt = "all" if save_on_exit == "all" else save_on_exit
                if fmt == "all":
                    paths = session.export_all()
                    for f, p in paths.items():
                        console.print(f"[green]✓[/green] {p}")
                else:
                    path = session.export_current(format=fmt)
                    if path:
                        console.print(f"[green]✓[/green] {path}")

    console.print("\n[dim]👋 종료합니다.[/dim]")


# ─── 명령어: schema ───────────────────────────────────────────────────────────


@app.command("schema")
def cmd_schema(
    schema: list[str] = typer.Option(["public"], "--schema", "-s"),
    table: Optional[str] = typer.Option(None, "--table", "-t", help="특정 테이블만 표시"),
    format: str = typer.Option("table", "--format", "-f", help="표시 형식: table | text"),
):
    """데이터베이스 스키마를 표시합니다."""
    from pg2text.database import DatabaseClient

    setup_logging()
    db = DatabaseClient()

    with console.status("스키마 로딩..."):
        if not db.test_connection():
            console.print("[red]DB 연결 실패[/red]")
            raise typer.Exit(1)
        db.load_schemas(schemas=list(schema), include_tables=[table] if table else None)

    if format == "text":
        console.print(db.schema_prompt())
    else:
        for tbl in db.schemas.values():
            t = Table(title=f"[bold]{tbl.full_name}[/bold]", show_header=True)
            t.add_column("컬럼", style="cyan")
            t.add_column("타입", style="yellow")
            t.add_column("NULL 허용")
            t.add_column("키")
            for col in tbl.columns:
                pk = "PK" if col.name in tbl.primary_keys else ""
                t.add_row(col.name, col.type, "O" if col.nullable else "X", pk)
            console.print(t)
            if tbl.comment:
                console.print(f"[dim]{tbl.comment}[/dim]")
            console.print()

    db.close()


# ─── 명령어: loan-demo ───────────────────────────────────────────────────────


@app.command("loan-demo")
def cmd_loan_demo(
    question: str = typer.Argument(
        "이번 달 개인여신 연체 관련 특이사항을 찾아줘",
        help="개인여신 업무 질문",
    ),
    schema: list[str] = typer.Option(["public"], "--schema", "-s", help="대상 스키마"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="보고서 저장 경로"),
    show_sql: bool = typer.Option(True, "--show-sql/--no-sql", help="실행 SQL 표시"),
):
    """
    개인여신 AI Data Workbench 1차 PoC 시나리오를 실행합니다.

    사전 준비:
        psql ... -f examples/mock_personal_loan_data.sql
    """
    from pg2text.database import DatabaseClient
    from pg2text.doc_builder import DocumentBuilder
    from pg2text.workbench import PersonalLoanWorkbench

    setup_logging()
    console.print(
        Panel.fit(
            "[bold cyan]개인여신 AI Data Workbench[/bold cyan]\n"
            "[dim]작은 단위 실행 → 검증 → 재실행 기준 확인[/dim]",
            border_style="cyan",
        )
    )
    console.print(f"\n[bold]질문:[/bold] {question}\n")

    db = DatabaseClient()
    workbench = PersonalLoanWorkbench()
    builder = DocumentBuilder()

    try:
        with console.status("DB 연결 및 스키마 로딩..."):
            if not db.test_connection():
                console.print("[red]DB 연결 실패[/red]")
                raise typer.Exit(1)
            db.load_schemas(schemas=list(schema))

        if workbench.table_name not in db.schemas:
            console.print(
                "[red]개인여신 샘플 테이블이 없습니다.[/red]\n"
                "먼저 [cyan]examples/mock_personal_loan_data.sql[/cyan]을 실행하세요."
            )
            raise typer.Exit(1)

        with console.status("시나리오 실행 중..."):
            result = workbench.run(question, db)

        console.print(Panel(result.plan.title, title="시나리오", border_style="blue"))
        console.print("[bold]분석 계획[/bold]")
        for idx, step in enumerate(result.plan.steps, 1):
            console.print(f"  {idx}. {step}")
        console.print(f"[dim]재실행 기준: {result.plan.rerun_policy}[/dim]\n")

        if show_sql:
            _print_sql(result.sql)

        if result.query_result.is_success and result.query_result.columns:
            console.print(f"\n[dim]조회 결과 ({result.query_result.row_count}건):[/dim]")
            _print_result_table(result.query_result.columns, result.query_result.rows)
        elif not result.query_result.is_success:
            console.print(f"[red]쿼리 오류:[/red] {result.query_result.error}")

        validation_table = Table(title="검증 결과", show_header=True)
        validation_table.add_column("검증")
        validation_table.add_column("상태")
        validation_table.add_column("상세")
        for item in result.validation_items:
            style = "green" if item.status == "통과" else "yellow"
            if item.status == "불일치":
                style = "red"
            validation_table.add_row(item.name, f"[{style}]{item.status}[/{style}]", item.detail)
        console.print(validation_table)

        console.print(
            Panel(
                Markdown(result.document.markdown_content),
                title=f"📄 {result.document.title}",
                border_style="green",
            )
        )

        saved = builder.save(result.document, format="md", output_path=output)
        console.print(f"\n[green]✓[/green] 저장 완료: [cyan]{saved}[/cyan]")

    finally:
        db.close()


# ─── 명령어: version ─────────────────────────────────────────────────────────


@app.command("version")
def cmd_version():
    """버전 정보를 표시합니다."""
    from pg2text import __version__
    console.print(f"pg2text [bold]{__version__}[/bold]")


if __name__ == "__main__":
    app()
