-- Personal loan AI Data Workbench demo schema and data
-- Run:
--   psql -h localhost -p 5432 -U <user> -d <db> -f examples/mock_personal_loan_data.sql

BEGIN;

DROP TABLE IF EXISTS public.personal_loan_mart CASCADE;

CREATE TABLE public.personal_loan_mart (
    base_month DATE NOT NULL,
    product_code TEXT NOT NULL,
    product_name TEXT NOT NULL,
    product_group TEXT NOT NULL,
    balance_amount NUMERIC(18, 2) NOT NULL CHECK (balance_amount >= 0),
    delinquent_amount_1m NUMERIC(18, 2) NOT NULL CHECK (delinquent_amount_1m >= 0),
    delinquency_rate_1m NUMERIC(8, 4) NOT NULL CHECK (delinquency_rate_1m >= 0),
    substandard_amount NUMERIC(18, 2) NOT NULL CHECK (substandard_amount >= 0),
    average_rate NUMERIC(8, 4) NOT NULL CHECK (average_rate >= 0),
    account_count INTEGER NOT NULL CHECK (account_count >= 0),
    mapped_yn BOOLEAN NOT NULL DEFAULT TRUE,
    source_report TEXT NOT NULL DEFAULT '개인여신 월간 특이사항 보고',
    PRIMARY KEY (base_month, product_code)
);

COMMENT ON TABLE public.personal_loan_mart IS
    '개인여신 AI Data Workbench PoC용 상품별 월간 집계 마트';
COMMENT ON COLUMN public.personal_loan_mart.base_month IS '기준월';
COMMENT ON COLUMN public.personal_loan_mart.balance_amount IS '상품별 월말 잔액';
COMMENT ON COLUMN public.personal_loan_mart.delinquent_amount_1m IS '1개월 이상 연체금액';
COMMENT ON COLUMN public.personal_loan_mart.delinquency_rate_1m IS
    '1개월 이상 연체율(%)';
COMMENT ON COLUMN public.personal_loan_mart.substandard_amount IS '고정이하여신합계';
COMMENT ON COLUMN public.personal_loan_mart.mapped_yn IS '상품코드 보고서 매핑 여부';

CREATE INDEX idx_personal_loan_mart_month
    ON public.personal_loan_mart (base_month);
CREATE INDEX idx_personal_loan_mart_group
    ON public.personal_loan_mart (product_group);

INSERT INTO public.personal_loan_mart (
    base_month,
    product_code,
    product_name,
    product_group,
    balance_amount,
    delinquent_amount_1m,
    delinquency_rate_1m,
    substandard_amount,
    average_rate,
    account_count,
    mapped_yn
) VALUES
    ('2026-02-28', 'PL001', '인터넷신용대출 A', '인터넷대출', 9200000000, 145000000, 1.5761, 41000000, 5.1200, 12400, TRUE),
    ('2026-02-28', 'PL002', '인터넷신용대출 B', '인터넷대출', 4300000000, 86000000, 2.0000, 28000000, 5.4500, 7100, TRUE),
    ('2026-02-28', 'PL003', '주택담보대출 기본', '주담대', 28400000000, 112000000, 0.3944, 35000000, 3.9200, 5200, TRUE),
    ('2026-02-28', 'PL004', '전세자금대출', '전세대출', 12200000000, 65000000, 0.5328, 21000000, 4.0100, 3900, TRUE),
    ('2026-02-28', 'PL005', '모바일간편대출', '인터넷대출', 2100000000, 72000000, 3.4286, 22000000, 6.1200, 8500, TRUE),
    ('2026-02-28', 'PL006', '생활안정대출', '기타', 3600000000, 58000000, 1.6111, 17000000, 5.7200, 4700, TRUE),

    ('2026-03-31', 'PL001', '인터넷신용대출 A', '인터넷대출', 9500000000, 152000000, 1.6000, 43000000, 5.2100, 12650, TRUE),
    ('2026-03-31', 'PL002', '인터넷신용대출 B', '인터넷대출', 4400000000, 91000000, 2.0682, 31000000, 5.5100, 7200, TRUE),
    ('2026-03-31', 'PL003', '주택담보대출 기본', '주담대', 28650000000, 118000000, 0.4119, 36000000, 3.9500, 5250, TRUE),
    ('2026-03-31', 'PL004', '전세자금대출', '전세대출', 12100000000, 69000000, 0.5702, 23000000, 4.0500, 3880, TRUE),
    ('2026-03-31', 'PL005', '모바일간편대출', '인터넷대출', 2050000000, 76000000, 3.7073, 24000000, 6.1800, 8420, TRUE),
    ('2026-03-31', 'PL006', '생활안정대출', '기타', 3620000000, 61000000, 1.6851, 19000000, 5.7600, 4720, TRUE),

    ('2026-04-30', 'PL001', '인터넷신용대출 A', '인터넷대출', 9810000000, 188000000, 1.9164, 57000000, 5.3700, 12910, TRUE),
    ('2026-04-30', 'PL002', '인터넷신용대출 B', '인터넷대출', 4520000000, 131000000, 2.8982, 49000000, 5.8300, 7280, TRUE),
    ('2026-04-30', 'PL003', '주택담보대출 기본', '주담대', 28900000000, 124000000, 0.4291, 38000000, 4.0200, 5300, TRUE),
    ('2026-04-30', 'PL004', '전세자금대출', '전세대출', 11900000000, 72000000, 0.6050, 25000000, 4.1100, 3840, TRUE),
    ('2026-04-30', 'PL005', '모바일간편대출', '인터넷대출', 1980000000, 103000000, 5.2020, 41000000, 6.6500, 8300, TRUE),
    ('2026-04-30', 'PL006', '생활안정대출', '기타', 3590000000, 66000000, 1.8384, 21000000, 5.9100, 4680, TRUE),
    ('2026-04-30', 'PL999', '신규코드 미매핑 상품', '기타', 670000000, 21000000, 3.1343, 9000000, 6.3000, 220, FALSE);

ANALYZE public.personal_loan_mart;

COMMIT;

SELECT base_month, COUNT(*) AS product_count
FROM public.personal_loan_mart
GROUP BY base_month
ORDER BY base_month;
