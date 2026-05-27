"""
문서 생성 모듈 테스트
"""

import pytest
from pathlib import Path
from pg2text.doc_builder import MarkdownBuilder, DocxBuilder, DocumentBuilder
from pg2text.nl_processor import GeneratedDocument


# ─── 테스트 픽스처 ────────────────────────────────────────────────────────────


@pytest.fixture
def sample_document() -> GeneratedDocument:
    return GeneratedDocument(
        title="월간 매출 분석 보고서",
        markdown_content="""# 월간 매출 분석 보고서

## 요약
2024년 1월 매출 데이터를 분석한 결과, 전월 대비 **15.3%** 증가를 기록했습니다.

## 데이터 분석

| 제품명 | 판매량 | 매출액 |
|--------|--------|--------|
| 제품 A | 1,200 | 6,000,000 |
| 제품 B | 800 | 4,800,000 |
| 제품 C | 650 | 2,925,000 |

## 핵심 인사이트

- 제품 A가 전체 매출의 44%를 차지
- 제품 C는 전월 대비 신규 진입하여 빠른 성장세
- 프리미엄 제품군 매출 비중 증가 추세

## 결론
전반적으로 긍정적인 성장세를 보이고 있으며, 제품 A에 대한 마케팅 강화가 권장됩니다.
""",
        metadata={"user_request": "월간 매출 보고서 작성"},
    )


# ─── Markdown 빌더 테스트 ─────────────────────────────────────────────────────


class TestMarkdownBuilder:
    def test_save_creates_file(self, tmp_path, sample_document):
        builder = MarkdownBuilder()
        output_path = tmp_path / "test_report.md"
        result = builder.save(sample_document, output_path)

        assert result == output_path
        assert output_path.exists()

    def test_save_contains_content(self, tmp_path, sample_document):
        builder = MarkdownBuilder()
        output_path = tmp_path / "test_report.md"
        builder.save(sample_document, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "월간 매출 분석 보고서" in content
        assert "제품 A" in content

    def test_save_includes_metadata_header(self, tmp_path, sample_document):
        builder = MarkdownBuilder()
        output_path = tmp_path / "test_report.md"
        builder.save(sample_document, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "title:" in content
        assert "generated_at:" in content

    def test_auto_filename_generation(self, tmp_path, sample_document, monkeypatch):
        """output_path 미지정 시 자동 파일명 생성"""
        from pg2text import config as cfg
        monkeypatch.setattr(cfg.settings, "pg2text_output_dir", tmp_path)

        builder = MarkdownBuilder()
        result = builder.save(sample_document)

        assert result.exists()
        assert result.suffix == ".md"
        assert "월간" in result.stem or "report" in result.stem.lower()


# ─── Word 빌더 테스트 ─────────────────────────────────────────────────────────


class TestDocxBuilder:
    def test_save_creates_file(self, tmp_path, sample_document):
        builder = DocxBuilder()
        output_path = tmp_path / "test_report.docx"
        result = builder.save(sample_document, output_path)

        assert result == output_path
        assert output_path.exists()
        assert output_path.stat().st_size > 0

    def test_save_is_valid_docx(self, tmp_path, sample_document):
        """생성된 파일이 유효한 .docx인지 확인"""
        from docx import Document as DocxDoc

        builder = DocxBuilder()
        output_path = tmp_path / "test_report.docx"
        builder.save(sample_document, output_path)

        # python-docx로 파일을 다시 열어 유효성 확인
        doc = DocxDoc(str(output_path))
        full_text = "\n".join(p.text for p in doc.paragraphs)
        assert "월간 매출 분석 보고서" in full_text

    def test_strip_inline_md(self):
        builder = DocxBuilder()
        assert builder._strip_inline_md("**굵게** 텍스트") == "굵게 텍스트"
        assert builder._strip_inline_md("`코드`") == "코드"
        assert builder._strip_inline_md("[링크](http://example.com)") == "링크"


# ─── DocumentBuilder 팩토리 테스트 ───────────────────────────────────────────


class TestDocumentBuilder:
    def test_save_md(self, tmp_path, sample_document):
        builder = DocumentBuilder()
        path = builder.save(sample_document, format="md", output_path=tmp_path / "r.md")
        assert path.suffix == ".md"

    def test_save_docx(self, tmp_path, sample_document):
        builder = DocumentBuilder()
        path = builder.save(sample_document, format="docx", output_path=tmp_path / "r.docx")
        assert path.suffix == ".docx"

    def test_invalid_format(self, tmp_path, sample_document):
        builder = DocumentBuilder()
        with pytest.raises(ValueError, match="지원하지 않는 형식"):
            builder.save(sample_document, format="pdf")

    def test_save_all(self, tmp_path, sample_document, monkeypatch):
        from pg2text import config as cfg
        monkeypatch.setattr(cfg.settings, "pg2text_output_dir", tmp_path)

        builder = DocumentBuilder()
        results = builder.save_all(sample_document)

        assert "md" in results
        assert "docx" in results
        assert results["md"].exists()
        assert results["docx"].exists()
