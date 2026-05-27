"""
대화 모듈 테스트
"""

import pytest
from pg2text.conversation import classify_intent, ConversationHistory, Message


# ─── 인텐트 분류 테스트 ───────────────────────────────────────────────────────


class TestClassifyIntent:
    def test_query_keywords(self):
        cases = [
            "매출 현황 보여줘",
            "최근 30일 주문 목록 조회해줘",
            "상품별 판매량 통계 알려줘",
            "how many orders were placed last month",
        ]
        for text in cases:
            result = classify_intent(text, has_current_document=False)
            assert result == "query", f"'{text}' → expected query, got {result}"

    def test_edit_keywords_with_document(self):
        cases = [
            "요약을 더 짧게 수정해줘",
            "인사이트 섹션 추가해줘",
            "결론 부분 삭제해줘",
            "make it shorter",
        ]
        for text in cases:
            result = classify_intent(text, has_current_document=True)
            assert result == "edit", f"'{text}' → expected edit, got {result}"

    def test_edit_without_document_becomes_query(self):
        """문서가 없으면 편집 요청도 다른 인텐트로 처리"""
        result = classify_intent("요약을 짧게 해줘", has_current_document=False)
        # 문서가 없으면 query나 info로 분류 (edit 아님)
        assert result != "edit"

    def test_export_keywords(self):
        cases = [
            "저장해줘",
            "export as docx",
            "워드 파일로 내보내",
            "md 파일로 저장",
        ]
        for text in cases:
            result = classify_intent(text, has_current_document=True)
            assert result == "export", f"'{text}' → expected export, got {result}"

    def test_info_fallback(self):
        """분류 불가 입력은 info로 처리"""
        result = classify_intent("안녕하세요", has_current_document=False)
        assert result == "info"


# ─── ConversationHistory 테스트 ───────────────────────────────────────────────


class TestConversationHistory:
    def test_add_and_retrieve(self):
        history = ConversationHistory(window=10)
        history.add("user", "안녕하세요")
        history.add("assistant", "안녕하세요! 무엇을 도와드릴까요?")

        msgs = history.to_api_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_window_limit(self):
        """window 크기 초과 시 오래된 메시지 제거"""
        history = ConversationHistory(window=3)
        for i in range(5):
            history.add("user", f"메시지 {i}")

        assert len(history) == 3
        msgs = history.to_api_messages()
        assert "메시지 2" in msgs[0]["content"]  # 앞 2개는 제거됨

    def test_save_and_load(self, tmp_path):
        history = ConversationHistory(window=10)
        history.add("user", "첫 번째 질문")
        history.add("assistant", "첫 번째 답변")

        save_path = tmp_path / "history.jsonl"
        history.save(save_path)

        loaded = ConversationHistory.load(save_path, window=10)
        msgs = loaded.to_api_messages()
        assert len(msgs) == 2
        assert msgs[0]["content"] == "첫 번째 질문"

    def test_clear(self):
        history = ConversationHistory(window=10)
        history.add("user", "test")
        history.clear()
        assert len(history) == 0

    def test_metadata_preserved(self):
        history = ConversationHistory(window=10)
        history.add("user", "test", sql="SELECT 1", doc_title="제목")
        # API 메시지에는 content만 포함
        msgs = history.to_api_messages()
        assert msgs[0] == {"role": "user", "content": "test"}
