from pg2text.semantic import default_personal_loan_semantic_layer


def test_semantic_prompt_contains_core_terms():
    layer = default_personal_loan_semantic_layer()
    prompt = layer.to_prompt_context()

    assert "개인여신 Semantic Layer" in prompt
    assert "연체금액" in prompt
    assert "고정이하여신" in prompt
    assert "1개월 이상 연체율" in prompt


def test_find_terms_matches_synonyms():
    layer = default_personal_loan_semantic_layer()
    terms = layer.find_terms("인터넷대출상품 중 연체 비중이 높은 상품을 찾아줘")

    assert [term.name for term in terms] == ["연체금액", "인터넷대출"]
