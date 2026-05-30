from pg2text.database import QueryResult
from pg2text.workbench import PersonalLoanWorkbench


def test_build_plan_for_monthly_anomaly():
    workbench = PersonalLoanWorkbench()

    plan = workbench.build_plan("이번 달 개인여신 연체 관련 특이사항을 찾아줘")

    assert plan.scenario == "monthly_anomaly"
    assert "최근 기준월 식별" in plan.steps
    assert "연체금액" in plan.matched_terms


def test_build_plan_for_high_ratio_query():
    workbench = PersonalLoanWorkbench()

    plan = workbench.build_plan("잔액은 크지 않은데 연체 비중이 높은 상품을 찾아줘")
    sql = workbench.build_sql(plan)

    assert plan.scenario == "high_ratio_low_balance"
    assert "delinquency_ratio_pct" in sql
    assert "personal_loan_mart" in sql


def test_validation_flags_spike_and_unmapped():
    workbench = PersonalLoanWorkbench()
    result = QueryResult(
        sql="SELECT ...",
        columns=[
            "product_code",
            "product_name",
            "balance_amount",
            "delinquent_amount_1m",
            "delinquent_change_pct",
            "mapped_yn",
        ],
        rows=[
            ("PL002", "인터넷신용대출 B", 4520000000, 131000000, 44.0, True),
            ("PL999", "신규코드 미매핑 상품", 670000000, 21000000, 0.0, False),
        ],
        row_count=2,
    )

    items = workbench.validate_result(result)

    statuses = {item.name: item.status for item in items}
    assert statuses["결과 존재"] == "통과"
    assert statuses["미매핑 검증"] == "확인 필요"
    assert statuses["전월 대비 검증"] == "확인 필요"


def test_report_uses_non_deterministic_language_policy():
    workbench = PersonalLoanWorkbench()
    plan = workbench.build_plan("이번 달 개인여신 연체 관련 특이사항을 찾아줘")
    result = QueryResult(
        sql="SELECT ...",
        columns=[
            "base_month",
            "product_name",
            "balance_amount",
            "delinquent_amount_1m",
            "delinquency_rate_1m",
            "delinquent_change_pct",
            "mapped_yn",
        ],
        rows=[
            ("2026-04-30", "인터넷신용대출 B", 4520000000, 131000000, 2.8982, 44.0, True),
        ],
        row_count=1,
    )
    validation_items = workbench.validate_result(result)

    document = workbench.build_report(
        "이번 달 개인여신 연체 관련 특이사항을 찾아줘",
        plan,
        result,
        validation_items,
    )

    assert "보고서 반영 후보" in document.markdown_content
    assert "원인 확정이 아니라" in document.markdown_content
    assert "재실행 기준" in document.markdown_content
    assert "검증 전 Semantic Layer" in document.markdown_content
    assert document.metadata["unapproved_semantic_items"]
