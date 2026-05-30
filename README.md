# postgresql2Text 🗄️→📄

**자연어로 PostgreSQL 데이터를 조회하고, 대화형으로 문서를 작성·수정하는 도구**

Gemini API가 자연어를 SQL로 변환하고, 조회 결과를 전문적인 보고서(Markdown / Word)로 작성합니다.  
대화를 통해 문서를 반복적으로 수정·보완할 수 있습니다.

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| 🔍 **자연어 → SQL** | "지난달 매출 TOP 10" 같은 자연어를 SQL로 변환 |
| 📊 **데이터 분석 문서** | 조회 결과를 구조화된 보고서로 자동 작성 |
| ✏️ **대화형 문서 편집** | "요약 더 짧게 해줘" 같은 자연어로 문서 수정 |
| 💾 **다양한 출력 형식** | Markdown (`.md`) / Word (`.docx`) 저장 |
| 🔄 **멀티턴 대화** | 대화 기록을 유지하며 연속적인 작업 지원 |

---

## 아키텍처

```
사용자 (자연어 입력)
       │
       ▼
┌──────────────────┐
│  InteractiveSession │  대화 상태 관리 / 인텐트 분류
└──┬───────────────┘
   │
   ├── [데이터 조회 요청]
   │      │
   │      ▼
   │   NLProcessor ──────→ Gemini API ──→ SQL 생성
   │      │
   │      ▼
   │   DatabaseClient ──→ PostgreSQL ──→ 데이터 반환
   │      │
   │      ▼
   │   NLProcessor ──────→ Gemini API ──→ 문서 작성
   │
   ├── [문서 편집 요청]
   │      │
   │      ▼
   │   NLProcessor ──────→ Gemini API ──→ 문서 수정
   │
   └── [내보내기 요청]
          │
          ▼
       DocumentBuilder ──→ .md / .docx 파일 저장
```

---

## 설치

### 요구사항

- Python 3.10+
- PostgreSQL 12+
- Gemini API Key

### 설치 방법

```bash
# 저장소 클론
git clone https://github.com/jamp0824/postgresql2text.git
cd postgresql2text

# 패키지 설치
pip install -e .

# 환경변수 설정
cp .env.example .env
# .env 파일을 편집해서 DB 정보와 API 키를 입력하세요
```

### `.env` 설정

```ini
# Gemini API Key (필수)
GEMINI_API_KEY=

# PostgreSQL 연결 정보 (필수)
PG_HOST=localhost
PG_PORT=5432
PG_DATABASE=mydb
PG_USER=postgres
PG_PASSWORD=your_password

# 선택 설정
PG2TEXT_MODEL=gemini-3.5-flash
PG2TEXT_OUTPUT_DIR=./output
```

---

## 사용법

### 1. 연결 테스트

```bash
pg2text connect
```

```
✓ 연결 성공!
테이블 8개 로딩 완료
  • public.orders
  • public.customers
  • public.products
  ...
```

### 2. 단일 쿼리 실행

```bash
# 자연어로 데이터 조회 후 Markdown 문서 생성
pg2text query "지난 30일간 가장 많이 팔린 제품 TOP 10 보고서 작성해줘"

# Word 문서로 저장
pg2text query "부서별 직원 현황 보고서" --format docx

# 파일 경로 직접 지정
pg2text query "월별 매출 추이" --output ./reports/monthly_sales.md
```

### 3. 대화형 세션 (권장)

```bash
pg2text chat
```

```
💡 도움말
• 데이터 조회: "지난달 매출 TOP 10 보고서 작성해줘"
• 문서 편집: "요약을 더 간결하게 수정해줘"
• 문서 저장: "저장해줘" / "워드 파일로 저장"
• 종료: exit 또는 Ctrl+C

> 2024년 분기별 매출 현황 보고서 작성해줘

[생성된 SQL]
SELECT quarter, SUM(amount) as revenue ...

✓ 48건 조회됨

📄 2024년 분기별 매출 현황 보고서
---
## 요약
2024년 전체 매출은 ...

> 인사이트를 좀 더 자세하게 써줘

✏️ 문서 수정됨

> md 파일로 저장해줘
✓ [MD] → ./output/2024년_분기별_매출_현황_보고서_20241201.md
```

### 4. 스키마 확인

```bash
# 전체 스키마 표시
pg2text schema

# 특정 테이블만
pg2text schema --table orders

# 텍스트 형식
pg2text schema --format text
```

### 5. 개인여신 AI Data Workbench PoC

작은 단위로 실행 → 검증 → 재실행 기준 확인이 가능한 개인여신 데모입니다.
기본 내장 Semantic Layer와 샘플 마트 데이터는 **검증 전 PoC 샘플**이며,
업무 확정값이나 공식 산식으로 사용하면 안 됩니다.

```bash
# 샘플 개인여신 마트 생성
psql -h localhost -p 5432 -U <user> -d <db> -f examples/mock_personal_loan_data.sql

# 월간 특이사항 자동 도출
pg2text loan-demo "이번 달 개인여신 연체 관련 특이사항을 찾아줘"

# 보고서명 없이 필요한 데이터 조회
pg2text loan-demo "잔액은 크지 않은데 연체 비중이 높은 상품을 찾아줘"

# 데이터 검증
pg2text loan-demo "이번 달 수치가 이상한데 검증해줘"

# 출처/승인상태가 포함된 Semantic Layer 파일을 명시해서 실행
pg2text loan-demo \
  "이번 달 개인여신 연체 관련 특이사항을 찾아줘" \
  --semantic-layer examples/semantic_layer.sample.json
```

PoC 범위는 `AI-Ready DB마트 샘플`, `Semantic Layer`, `분석계획`, `검증 결과`,
`보고서 초안`까지입니다. Lineage, 중복 SQL 탐지, 테스트 케이스 자동 생성은 2차
고도화 항목으로 분리했습니다.

실제 업무 적용 전에는 `ADW 기존 SQL`, `정형보고서`, `데이터 사전`,
`현업 승인 산식표`를 근거로 Semantic Layer를 구성하고, 각 항목에
`source_type`, `source_name`, `owner`, `approval_status`를 포함해야 합니다.
`approval_status=approved`가 아닌 항목은 보고서에서 검토 후보로만 취급해야 합니다.

---

## 지원 출력 형식

| 형식 | 확장자 | 설명 |
|------|--------|------|
| Markdown | `.md` | YAML 헤더 포함, GitHub 렌더링 지원 |
| Word | `.docx` | 스타일 적용, 한글 폰트(맑은 고딕) |

---

## 사용된 오픈소스 기술

| 라이브러리 | 역할 |
|-----------|------|
| [Google Gen AI SDK](https://googleapis.github.io/python-genai/) | Gemini API 연동 (NL→SQL, 문서 생성) |
| [SQLAlchemy](https://www.sqlalchemy.org/) | PostgreSQL 연결 및 스키마 인트로스펙션 |
| [psycopg2](https://www.psycopg.org/) | PostgreSQL 드라이버 |
| [python-docx](https://python-docx.readthedocs.io/) | Word(.docx) 문서 생성 |
| [Typer](https://typer.tiangolo.com/) | CLI 인터페이스 |
| [Rich](https://rich.readthedocs.io/) | 터미널 UI (표, 패널, 스피너) |
| [Pydantic](https://docs.pydantic.dev/) | 설정 및 데이터 검증 |

---

## 프로젝트 구조

```
postgresql2Text/
├── src/
│   └── pg2text/
│       ├── __init__.py
│       ├── config.py          # 환경변수 설정 (pydantic-settings)
│       ├── database.py        # PostgreSQL 연결, 스키마 로딩, 쿼리 실행
│       ├── nl_processor.py    # Gemini API — NL→SQL, 문서 생성/편집
│       ├── doc_builder.py     # Markdown / Word 문서 빌더
│       ├── conversation.py    # 대화 세션 관리, 인텐트 분류
│       └── cli.py             # Typer CLI 진입점
├── tests/
│   ├── test_database.py
│   ├── test_conversation.py
│   └── test_doc_builder.py
├── examples/
│   └── demo_session.py
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 보안

- **SELECT 전용**: INSERT/UPDATE/DELETE/DROP 등 DML/DDL은 실행 차단
- **환경변수 분리**: API 키와 DB 비밀번호는 `.env` 파일로 관리
- **대화 기록**: 로컬 파일에만 저장, 외부 전송 없음

---

## 라이선스

MIT License
