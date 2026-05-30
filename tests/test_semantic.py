import json

from pg2text.semantic import SemanticLayer, default_personal_loan_semantic_layer


def test_semantic_prompt_contains_core_terms():
    layer = default_personal_loan_semantic_layer()
    prompt = layer.to_prompt_context()

    assert "개인여신 Semantic Layer" in prompt
    assert "연체금액" in prompt
    assert "고정이하여신" in prompt
    assert "1개월 이상 연체율" in prompt
    assert "검증 전 Semantic Layer" in prompt
    assert "demo_unverified" in prompt


def test_find_terms_matches_synonyms():
    layer = default_personal_loan_semantic_layer()
    terms = layer.find_terms("인터넷대출상품 중 연체 비중이 높은 상품을 찾아줘")

    assert [term.name for term in terms] == ["연체금액", "인터넷대출"]


def test_default_layer_is_not_approved():
    layer = default_personal_loan_semantic_layer()

    assert layer.has_unapproved_items
    assert "업무 확정값" in layer.trust_notice()


def test_load_semantic_layer_from_json(tmp_path):
    path = tmp_path / "semantic_layer.json"
    path.write_text(
        json.dumps(
            {
                "layer_name": "approved_test_layer",
                "business_terms": [
                    {
                        "name": "잔액",
                        "synonyms": ["대출잔액"],
                        "description": "승인된 테스트 정의",
                        "metrics": ["잔액"],
                        "source": {
                            "source_type": "approved_formula",
                            "source_name": "현업 승인 산식표 v1",
                            "owner": "개인여신부",
                            "approval_status": "approved",
                            "verified_at": "2026-05-31",
                        },
                    }
                ],
                "metrics": [
                    {
                        "name": "잔액",
                        "column": "balance_amount",
                        "formula": "승인된 잔액 산식",
                        "base_date_rule": "월말",
                        "description": "승인된 테스트 지표",
                        "source": {
                            "source_type": "approved_formula",
                            "source_name": "현업 승인 산식표 v1",
                            "owner": "개인여신부",
                            "approval_status": "approved",
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    layer = SemanticLayer.from_json_file(path)

    assert layer.layer_name == "approved_test_layer"
    assert not layer.has_unapproved_items
    assert layer.find_terms("대출잔액 알려줘", approved_only=True)[0].name == "잔액"
