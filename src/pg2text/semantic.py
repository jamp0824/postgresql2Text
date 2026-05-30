"""
개인여신 AI Workbench용 최소 Semantic Layer.

운영 메타데이터 저장소를 만들기 전, PoC에서 프롬프트/분석계획/검증에
동일한 업무 정의를 재사용하기 위한 작은 인메모리 모델입니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusinessTerm:
    name: str
    synonyms: tuple[str, ...]
    description: str
    metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    column: str
    formula: str
    base_date_rule: str
    description: str


@dataclass(frozen=True)
class ReportMetadata:
    name: str
    cycle: str
    metrics: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class AnalysisTemplate:
    name: str
    intent_keywords: tuple[str, ...]
    steps: tuple[str, ...]
    output_items: tuple[str, ...]


@dataclass(frozen=True)
class SemanticLayer:
    business_terms: tuple[BusinessTerm, ...] = field(default_factory=tuple)
    metrics: tuple[MetricDefinition, ...] = field(default_factory=tuple)
    reports: tuple[ReportMetadata, ...] = field(default_factory=tuple)
    templates: tuple[AnalysisTemplate, ...] = field(default_factory=tuple)

    def to_prompt_context(self) -> str:
        """LLM에 넘길 수 있는 compact context."""
        parts = ["=== 개인여신 Semantic Layer ==="]
        parts.append("[업무용어]")
        for term in self.business_terms:
            synonyms = ", ".join(term.synonyms)
            metrics = ", ".join(term.metrics) if term.metrics else "-"
            parts.append(f"- {term.name}({synonyms}): {term.description} / 지표: {metrics}")

        parts.append("\n[지표/산식]")
        for metric in self.metrics:
            parts.append(
                f"- {metric.name}: column={metric.column}, 산식={metric.formula}, "
                f"기준일={metric.base_date_rule}"
            )

        parts.append("\n[보고서 메타데이터]")
        for report in self.reports:
            parts.append(
                f"- {report.name}: 주기={report.cycle}, "
                f"지표={', '.join(report.metrics)}, 설명={report.description}"
            )

        parts.append("\n[분석 템플릿]")
        for template in self.templates:
            parts.append(f"- {template.name}: {' → '.join(template.steps)}")

        return "\n".join(parts)

    def find_terms(self, text: str) -> list[BusinessTerm]:
        """질문에 등장한 업무용어를 찾습니다."""
        found: list[BusinessTerm] = []
        lowered = text.lower()
        for term in self.business_terms:
            candidates = (term.name, *term.synonyms)
            if any(candidate.lower() in lowered for candidate in candidates):
                found.append(term)
        return found


def default_personal_loan_semantic_layer() -> SemanticLayer:
    """2주 PoC용 기본 개인여신 의미 계층."""
    return SemanticLayer(
        business_terms=(
            BusinessTerm(
                name="잔액",
                synonyms=("대출잔액", "총잔액"),
                description="기준월 말 상품별 개인여신 잔액",
                metrics=("잔액",),
            ),
            BusinessTerm(
                name="연체금액",
                synonyms=("1개월 이상 연체금액", "연체"),
                description="1개월 이상 연체로 분류된 금액",
                metrics=("1개월 이상 연체금액", "1개월 이상 연체율"),
            ),
            BusinessTerm(
                name="고정이하여신",
                synonyms=("고정이하", "건전성"),
                description="건전성 분류상 고정 이하로 분류된 여신",
                metrics=("고정이하여신합계",),
            ),
            BusinessTerm(
                name="주담대",
                synonyms=("주택담보대출", "담보대출"),
                description="주택담보 관련 개인여신 상품군",
                metrics=("잔액", "1개월 이상 연체금액", "LTV"),
            ),
            BusinessTerm(
                name="인터넷대출",
                synonyms=("인터넷대출상품", "비대면대출"),
                description="비대면 채널로 취급되는 개인여신 상품군",
                metrics=("잔액", "1개월 이상 연체금액", "평균금리"),
            ),
            BusinessTerm(
                name="월보",
                synonyms=("월간 업무보고", "월간 보고서"),
                description="월간 개인여신 주요 지표 보고서",
                metrics=("잔액", "1개월 이상 연체금액", "고정이하여신합계"),
            ),
        ),
        metrics=(
            MetricDefinition(
                name="잔액",
                column="balance_amount",
                formula="상품별 기준월 말 잔액 합계",
                base_date_rule="base_month 기준 월말",
                description="상품별 개인여신 잔액 규모",
            ),
            MetricDefinition(
                name="1개월 이상 연체금액",
                column="delinquent_amount_1m",
                formula="1개월 이상 연체 계좌의 잔액 합계",
                base_date_rule="base_month 기준 월말",
                description="연체 리스크 규모",
            ),
            MetricDefinition(
                name="1개월 이상 연체율",
                column="delinquency_rate_1m",
                formula="delinquent_amount_1m / balance_amount",
                base_date_rule="base_month 기준 월말",
                description="잔액 대비 연체금액 비중",
            ),
            MetricDefinition(
                name="고정이하여신합계",
                column="substandard_amount",
                formula="고정, 회수의문, 추정손실 분류 여신 합계",
                base_date_rule="base_month 기준 월말",
                description="건전성 악화 가능성 점검 지표",
            ),
            MetricDefinition(
                name="평균금리",
                column="average_rate",
                formula="상품별 가중평균 금리",
                base_date_rule="base_month 기준 월말",
                description="금리 변동 영향 확인 지표",
            ),
        ),
        reports=(
            ReportMetadata(
                name="개인여신 월간 특이사항 보고",
                cycle="월간",
                metrics=("잔액", "1개월 이상 연체금액", "고정이하여신합계", "평균금리"),
                description="월별 상품군 변동, 리스크 후보, 확인 필요사항 보고",
            ),
            ReportMetadata(
                name="연체/건전성 점검 리포트",
                cycle="수시",
                metrics=("1개월 이상 연체금액", "1개월 이상 연체율", "고정이하여신합계"),
                description="연체 증가와 건전성 악화 가능성 점검",
            ),
        ),
        templates=(
            AnalysisTemplate(
                name="월간 특이사항 자동 도출",
                intent_keywords=("특이사항", "이번 달", "월간", "연체"),
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
                    "확인 필요사항",
                    "보고서용 문장",
                ),
            ),
            AnalysisTemplate(
                name="보고서명 없는 데이터 조회",
                intent_keywords=("잔액", "연체 비중", "높은 상품"),
                steps=(
                    "잔액, 연체금액, 연체율 지표 식별",
                    "상품별 집계 데이터 조회",
                    "잔액 규모 필터링",
                    "연체금액/잔액 비율 계산",
                    "상위 상품 정렬",
                ),
                output_items=("상품 목록", "연체 비중", "리스크 후보 설명"),
            ),
            AnalysisTemplate(
                name="데이터 검증",
                intent_keywords=("검증", "수치", "이상"),
                steps=(
                    "전월 대비 급증/급감 확인",
                    "전년동월 대비 확인",
                    "상품코드 미매핑 확인",
                    "합계 불일치 확인",
                    "산식 변경 여부 점검",
                ),
                output_items=("검증 통과 항목", "확인 필요 항목", "검증 리포트"),
            ),
        ),
    )
