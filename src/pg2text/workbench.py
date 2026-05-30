"""
개인여신 AI Data Workbench MVP.

LLM이 없어도 3개 핵심 시나리오를 반복 검증할 수 있도록 질문 분류,
분석계획, SQL 템플릿, 검증, 보고서 초안 생성을 작은 단위로 제공합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pg2text.database import DatabaseClient, QueryResult
from pg2text.nl_processor import GeneratedDocument
from pg2text.semantic import SemanticLayer, default_personal_loan_semantic_layer


Scenario = Literal["monthly_anomaly", "high_ratio_low_balance", "validation", "report"]


@dataclass(frozen=True)
class WorkbenchPlan:
    scenario: Scenario
    title: str
    interpreted_question: str
    matched_terms: tuple[str, ...]
    steps: tuple[str, ...]
    output_items: tuple[str, ...]
    rerun_policy: str


@dataclass(frozen=True)
class ValidationItem:
    name: str
    status: Literal["통과", "확인 필요", "불일치"]
    detail: str


@dataclass(frozen=True)
class WorkbenchRunResult:
    plan: WorkbenchPlan
    sql: str
    query_result: QueryResult
    validation_items: tuple[ValidationItem, ...]
    document: GeneratedDocument


class PersonalLoanWorkbench:
    """개인여신 PoC 시나리오 실행기."""

    table_name = "public.personal_loan_mart"

    def __init__(self, semantic_layer: SemanticLayer | None = None):
        self.semantic_layer = semantic_layer or default_personal_loan_semantic_layer()

    def build_plan(self, question: str) -> WorkbenchPlan:
        scenario = self._classify_scenario(question)
        matched_terms = tuple(term.name for term in self.semantic_layer.find_terms(question))

        if scenario == "high_ratio_low_balance":
            return WorkbenchPlan(
                scenario=scenario,
                title="보고서명 없는 데이터 조회",
                interpreted_question="잔액 규모는 낮지만 연체 비중이 높은 상품 탐색",
                matched_terms=matched_terms or ("잔액", "연체금액"),
                steps=(
                    "잔액, 연체금액, 연체율 지표 식별",
                    "최근 기준월 상품별 집계 데이터 조회",
                    "평균 이하 잔액 상품으로 필터링",
                    "연체금액/잔액 비율 기준 상위 상품 정렬",
                    "리스크 후보 설명 생성",
                ),
                output_items=("상품 목록", "연체 비중", "잔액 규모", "리스크 후보"),
                rerun_policy="결과가 없으면 잔액 필터를 평균 이하에서 중위값 이하로 조정",
            )

        if scenario == "validation":
            return WorkbenchPlan(
                scenario=scenario,
                title="데이터 검증",
                interpreted_question="이번 달 개인여신 주요 수치 이상 여부 검증",
                matched_terms=matched_terms,
                steps=(
                    "전월 대비 급증/급감 확인",
                    "상품코드 미매핑 여부 확인",
                    "합계 및 산식 적용 여부 확인",
                    "기존 ADW SQL 대사 후보 항목 정리",
                    "검증 리포트 생성",
                ),
                output_items=("검증 통과 항목", "확인 필요 항목", "불일치 후보"),
                rerun_policy="확인 필요 항목이 있으면 해당 상품만 재조회",
            )

        if scenario == "report":
            return WorkbenchPlan(
                scenario=scenario,
                title="보고서 초안 작성",
                interpreted_question="조회 결과를 부장 보고용 문장으로 정리",
                matched_terms=matched_terms,
                steps=(
                    "핵심 지표 요약",
                    "주요 증감 항목 정리",
                    "리스크 포인트 도출",
                    "확인 필요사항 제시",
                    "근거 수치와 기준월 표시",
                ),
                output_items=("요약문", "보고서체 문장", "근거 지표"),
                rerun_policy="근거 수치가 없으면 보고서 초안 생성 중단",
            )

        return WorkbenchPlan(
            scenario="monthly_anomaly",
            title="월간 특이사항 자동 도출",
            interpreted_question="이번 달 개인여신 연체 관련 특이사항 도출",
            matched_terms=matched_terms or ("연체금액", "고정이하여신"),
            steps=(
                "최근 기준월 식별",
                "연체 관련 지표 조회",
                "전월 대비 증감률 계산",
                "증가 기여 상품 분석",
                "고정이하여신 동반 증가 여부 확인",
                "보고서 반영 후보 도출",
            ),
            output_items=(
                "연체금액 증가 상위 상품",
                "연체율 상승 상품",
                "고정이하여신 동반 증가 상품",
                "확인 필요사항",
            ),
            rerun_policy="SQL 실행 오류 시 월별 기준월 조회부터 재실행",
        )

    def build_sql(self, plan: WorkbenchPlan) -> str:
        if plan.scenario == "high_ratio_low_balance":
            return f"""
WITH latest AS (
    SELECT MAX(base_month) AS base_month FROM {self.table_name}
),
threshold AS (
    SELECT AVG(balance_amount) AS avg_balance
    FROM {self.table_name}
    WHERE base_month = (SELECT base_month FROM latest)
)
SELECT
    m.base_month,
    m.product_code,
    m.product_name,
    m.product_group,
    m.balance_amount,
    m.delinquent_amount_1m,
    ROUND((m.delinquent_amount_1m / NULLIF(m.balance_amount, 0)) * 100, 2)
        AS delinquency_ratio_pct,
    m.account_count
FROM {self.table_name} AS m
CROSS JOIN threshold AS t
WHERE m.base_month = (SELECT base_month FROM latest)
  AND m.balance_amount <= t.avg_balance
ORDER BY delinquency_ratio_pct DESC, m.delinquent_amount_1m DESC
LIMIT 10
""".strip()

        if plan.scenario == "validation":
            return f"""
WITH latest AS (
    SELECT MAX(base_month) AS base_month FROM {self.table_name}
),
current_month AS (
    SELECT * FROM {self.table_name}
    WHERE base_month = (SELECT base_month FROM latest)
),
previous_month AS (
    SELECT * FROM {self.table_name}
    WHERE base_month = (
        SELECT MAX(base_month) FROM {self.table_name}
        WHERE base_month < (SELECT base_month FROM latest)
    )
),
joined AS (
    SELECT
        c.product_code,
        c.product_name,
        c.balance_amount,
        c.delinquent_amount_1m,
        c.delinquency_rate_1m,
        c.mapped_yn,
        p.delinquent_amount_1m AS prev_delinquent_amount_1m
    FROM current_month AS c
    LEFT JOIN previous_month AS p ON p.product_code = c.product_code
)
SELECT
    product_code,
    product_name,
    balance_amount,
    delinquent_amount_1m,
    prev_delinquent_amount_1m,
    ROUND(
        ((delinquent_amount_1m - prev_delinquent_amount_1m)
        / NULLIF(prev_delinquent_amount_1m, 0)) * 100,
        2
    ) AS delinquent_change_pct,
    ROUND((delinquent_amount_1m / NULLIF(balance_amount, 0)) * 100, 2)
        AS recalculated_delinquency_rate_pct,
    delinquency_rate_1m,
    mapped_yn
FROM joined
WHERE mapped_yn = FALSE
   OR prev_delinquent_amount_1m IS NULL
   OR ABS(
        ROUND((delinquent_amount_1m / NULLIF(balance_amount, 0)) * 100, 2)
        - delinquency_rate_1m
      ) >= 0.05
   OR ((delinquent_amount_1m - prev_delinquent_amount_1m)
        / NULLIF(prev_delinquent_amount_1m, 0)) >= 0.2
ORDER BY delinquent_change_pct DESC NULLS LAST
""".strip()

        return f"""
WITH latest AS (
    SELECT MAX(base_month) AS base_month FROM {self.table_name}
),
current_month AS (
    SELECT * FROM {self.table_name}
    WHERE base_month = (SELECT base_month FROM latest)
),
previous_month AS (
    SELECT * FROM {self.table_name}
    WHERE base_month = (
        SELECT MAX(base_month) FROM {self.table_name}
        WHERE base_month < (SELECT base_month FROM latest)
    )
)
SELECT
    c.base_month,
    c.product_code,
    c.product_name,
    c.product_group,
    c.balance_amount,
    c.delinquent_amount_1m,
    p.delinquent_amount_1m AS prev_delinquent_amount_1m,
    c.delinquency_rate_1m,
    ROUND(
        ((c.delinquent_amount_1m - p.delinquent_amount_1m)
        / NULLIF(p.delinquent_amount_1m, 0)) * 100,
        2
    ) AS delinquent_change_pct,
    c.substandard_amount,
    p.substandard_amount AS prev_substandard_amount,
    c.average_rate,
    c.mapped_yn
FROM current_month AS c
LEFT JOIN previous_month AS p ON p.product_code = c.product_code
ORDER BY
    (c.delinquent_amount_1m - COALESCE(p.delinquent_amount_1m, 0)) DESC,
    c.delinquency_rate_1m DESC
LIMIT 10
""".strip()

    def validate_result(self, result: QueryResult) -> tuple[ValidationItem, ...]:
        if not result.is_success:
            return (
                ValidationItem("SQL 실행", "불일치", result.error or "알 수 없는 오류"),
            )

        items: list[ValidationItem] = []
        items.append(
            ValidationItem(
                "결과 존재",
                "통과" if result.row_count > 0 else "확인 필요",
                f"{result.row_count}건 조회",
            )
        )

        rows = result.to_dict_list()
        numeric_issues = []
        for row in rows:
            for key, value in row.items():
                if key.endswith("_amount") and value is not None and float(value) < 0:
                    numeric_issues.append(f"{row.get('product_code', '-')}.{key}")
        items.append(
            ValidationItem(
                "음수 금액 검증",
                "통과" if not numeric_issues else "불일치",
                "음수 금액 없음" if not numeric_issues else ", ".join(numeric_issues),
            )
        )

        unmapped = [
            str(row.get("product_code"))
            for row in rows
            if row.get("mapped_yn") is False
        ]
        items.append(
            ValidationItem(
                "미매핑 검증",
                "통과" if not unmapped else "확인 필요",
                "상품코드 미매핑 없음" if not unmapped else f"미매핑: {', '.join(unmapped)}",
            )
        )

        spike_products = []
        for row in rows:
            change = row.get("delinquent_change_pct")
            if change is not None and float(change) >= 20:
                spike_products.append(f"{row.get('product_name')} {change}%")
        items.append(
            ValidationItem(
                "전월 대비 검증",
                "통과" if not spike_products else "확인 필요",
                "20% 이상 급증 없음" if not spike_products else "; ".join(spike_products),
            )
        )
        return tuple(items)

    def build_report(
        self,
        question: str,
        plan: WorkbenchPlan,
        result: QueryResult,
        validation_items: tuple[ValidationItem, ...],
    ) -> GeneratedDocument:
        rows = result.to_dict_list()
        base_month = rows[0].get("base_month", "기준월 미확인") if rows else "기준월 미확인"
        top_rows = rows[:5]

        lines = [
            f"# {plan.title}",
            "",
            "## 질문 해석",
            f"- 원문 질문: {question}",
            f"- 해석: {plan.interpreted_question}",
            f"- 매핑 용어: {', '.join(plan.matched_terms) if plan.matched_terms else '없음'}",
            "",
            "## 분석 계획",
        ]
        lines.extend(f"{idx}. {step}" for idx, step in enumerate(plan.steps, 1))

        lines.extend(["", "## 주요 결과"])
        if top_rows:
            lines.append(
                "| 기준월 | 상품 | 잔액 | 1개월 이상 연체금액 | 연체율/비중 | 확인 포인트 |"
            )
            lines.append("| --- | --- | ---: | ---: | ---: | --- |")
            for row in top_rows:
                ratio = row.get("delinquency_ratio_pct", row.get("delinquency_rate_1m", "-"))
                change = row.get("delinquent_change_pct")
                point = "확인 필요" if change is not None and float(change) >= 20 else "모니터링"
                lines.append(
                    f"| {row.get('base_month', base_month)} | {row.get('product_name', '-')} | "
                    f"{row.get('balance_amount', '-')} | {row.get('delinquent_amount_1m', '-')} | "
                    f"{ratio} | {point} |"
                )
        else:
            lines.append("- 조회 결과가 없어 조건을 줄여 재실행해야 합니다.")

        lines.extend(["", "## 검증 결과"])
        for item in validation_items:
            lines.append(f"- {item.name}: {item.status} ({item.detail})")

        lines.extend(
            [
                "",
                "## 보고서 초안",
                self._draft_sentence(base_month, top_rows, validation_items),
                "",
                "## 재실행 기준",
                f"- {plan.rerun_policy}",
            ]
        )

        return GeneratedDocument(
            title=plan.title,
            markdown_content="\n".join(lines),
            query_results=[result],
            metadata={
                "user_request": question,
                "scenario": plan.scenario,
                "base_month": str(base_month),
                "validation": [item.__dict__ for item in validation_items],
            },
        )

    def run(self, question: str, db_client: DatabaseClient) -> WorkbenchRunResult:
        plan = self.build_plan(question)
        sql = self.build_sql(plan)
        query_result = db_client.execute(sql)
        validation_items = self.validate_result(query_result)
        document = self.build_report(question, plan, query_result, validation_items)
        return WorkbenchRunResult(
            plan=plan,
            sql=sql,
            query_result=query_result,
            validation_items=validation_items,
            document=document,
        )

    def _classify_scenario(self, question: str) -> Scenario:
        if any(keyword in question for keyword in ("검증", "이상한", "이상")):
            return "validation"
        if "잔액" in question and any(keyword in question for keyword in ("비중", "높은")):
            return "high_ratio_low_balance"
        if any(keyword in question for keyword in ("부장", "보고용", "정리")):
            return "report"
        return "monthly_anomaly"

    def _draft_sentence(
        self,
        base_month: object,
        rows: list[dict],
        validation_items: tuple[ValidationItem, ...],
    ) -> str:
        if not rows:
            return "조회 결과가 없어 보고서 초안을 생성하지 않았습니다."

        first = rows[0]
        product = first.get("product_name", "상위 상품")
        delinquent = first.get("delinquent_amount_1m", "-")
        change = first.get("delinquent_change_pct")
        check_items = [item.name for item in validation_items if item.status != "통과"]
        check_text = ", ".join(check_items) if check_items else "추가 확인 필요사항은 없습니다"
        change_text = f"전월 대비 {change}% 변동" if change is not None else "상위 수준"
        return (
            f"{base_month} 기준 {product}의 1개월 이상 연체금액은 {delinquent}이며 "
            f"{change_text}으로 나타났습니다. 해당 결과는 원인 확정이 아니라 "
            f"보고서 반영 후보이며, {check_text} 항목을 검토한 뒤 최종 문장으로 "
            "확정하는 것이 필요합니다."
        )
