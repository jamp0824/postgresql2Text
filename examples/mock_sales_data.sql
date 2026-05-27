-- pg2text demo schema and mock data
-- Run:
--   PGPASSWORD='junonan!' psql -h localhost -p 5432 -U junonan -d postgres -f examples/mock_sales_data.sql

BEGIN;

DROP TABLE IF EXISTS public.order_items CASCADE;
DROP TABLE IF EXISTS public.payments CASCADE;
DROP TABLE IF EXISTS public.orders CASCADE;
DROP TABLE IF EXISTS public.products CASCADE;
DROP TABLE IF EXISTS public.categories CASCADE;
DROP TABLE IF EXISTS public.customers CASCADE;

CREATE TABLE public.customers (
    customer_id BIGSERIAL PRIMARY KEY,
    customer_name TEXT NOT NULL,
    segment TEXT NOT NULL CHECK (segment IN ('Enterprise', 'SMB', 'Consumer')),
    region TEXT NOT NULL CHECK (region IN ('Seoul', 'Gyeonggi', 'Busan', 'Daegu', 'Daejeon', 'Gwangju', 'Jeju')),
    joined_at DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE public.categories (
    category_id BIGSERIAL PRIMARY KEY,
    category_name TEXT NOT NULL UNIQUE
);

CREATE TABLE public.products (
    product_id BIGSERIAL PRIMARY KEY,
    product_name TEXT NOT NULL,
    category_id BIGINT NOT NULL REFERENCES public.categories(category_id),
    list_price NUMERIC(12, 2) NOT NULL CHECK (list_price >= 0),
    active BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE public.orders (
    order_id BIGSERIAL PRIMARY KEY,
    customer_id BIGINT NOT NULL REFERENCES public.customers(customer_id),
    order_date DATE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('completed', 'cancelled', 'refunded')),
    channel TEXT NOT NULL CHECK (channel IN ('online', 'store', 'partner')),
    sales_rep TEXT NOT NULL
);

CREATE TABLE public.order_items (
    order_item_id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES public.orders(order_id) ON DELETE CASCADE,
    product_id BIGINT NOT NULL REFERENCES public.products(product_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    discount_rate NUMERIC(5, 4) NOT NULL DEFAULT 0 CHECK (discount_rate >= 0 AND discount_rate <= 1),
    line_amount NUMERIC(14, 2) GENERATED ALWAYS AS
        (ROUND((quantity * unit_price * (1 - discount_rate))::numeric, 2)) STORED
);

CREATE TABLE public.payments (
    payment_id BIGSERIAL PRIMARY KEY,
    order_id BIGINT NOT NULL REFERENCES public.orders(order_id) ON DELETE CASCADE,
    paid_at TIMESTAMP NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('card', 'bank_transfer', 'cash', 'points')),
    amount NUMERIC(14, 2) NOT NULL CHECK (amount >= 0)
);

CREATE INDEX idx_orders_order_date ON public.orders(order_date);
CREATE INDEX idx_orders_customer_id ON public.orders(customer_id);
CREATE INDEX idx_order_items_product_id ON public.order_items(product_id);
CREATE INDEX idx_products_category_id ON public.products(category_id);

COMMENT ON TABLE public.customers IS '데모 고객 마스터. 고객 세그먼트와 지역별 분석에 사용합니다.';
COMMENT ON TABLE public.products IS '데모 상품 마스터. 카테고리별/상품별 매출 분석에 사용합니다.';
COMMENT ON TABLE public.orders IS '데모 주문 헤더. 주문일, 상태, 채널, 영업 담당자를 포함합니다.';
COMMENT ON TABLE public.order_items IS '데모 주문 상세. 수량, 단가, 할인율, 매출액을 포함합니다.';
COMMENT ON TABLE public.payments IS '데모 결제 데이터. 결제수단별 매출 분석에 사용합니다.';

INSERT INTO public.categories (category_name) VALUES
    ('Software'),
    ('Hardware'),
    ('Service'),
    ('Training'),
    ('Subscription');

INSERT INTO public.products (product_name, category_id, list_price) VALUES
    ('Analytics Pro License', 1, 1200000),
    ('Data Studio License', 1, 850000),
    ('Cloud Backup Agent', 1, 320000),
    ('Edge Gateway', 2, 740000),
    ('POS Terminal', 2, 560000),
    ('Barcode Scanner', 2, 180000),
    ('Implementation Package', 3, 2500000),
    ('Maintenance Contract', 3, 950000),
    ('Onsite Consulting', 3, 1800000),
    ('Admin Training', 4, 450000),
    ('Developer Workshop', 4, 700000),
    ('Premium Support Monthly', 5, 290000),
    ('Enterprise Support Monthly', 5, 650000),
    ('Security Monitoring Monthly', 5, 380000);

INSERT INTO public.customers (customer_name, segment, region, joined_at)
SELECT
    'Customer ' || LPAD(n::text, 3, '0') AS customer_name,
    (ARRAY['Enterprise', 'SMB', 'Consumer'])[1 + (n % 3)] AS segment,
    (ARRAY['Seoul', 'Gyeonggi', 'Busan', 'Daegu', 'Daejeon', 'Gwangju', 'Jeju'])[1 + (n % 7)] AS region,
    CURRENT_DATE - ((n * 13) % 900)
FROM generate_series(1, 80) AS n;

INSERT INTO public.orders (customer_id, order_date, status, channel, sales_rep)
SELECT
    1 + ((n * 7) % 80) AS customer_id,
    (CURRENT_DATE - INTERVAL '18 months' + (n * INTERVAL '2 days'))::date AS order_date,
    CASE
        WHEN n % 23 = 0 THEN 'cancelled'
        WHEN n % 31 = 0 THEN 'refunded'
        ELSE 'completed'
    END AS status,
    (ARRAY['online', 'store', 'partner'])[1 + (n % 3)] AS channel,
    (ARRAY['Kim', 'Lee', 'Park', 'Choi', 'Jung'])[1 + (n % 5)] AS sales_rep
FROM generate_series(1, 270) AS n;

INSERT INTO public.order_items (order_id, product_id, quantity, unit_price, discount_rate)
SELECT
    o.order_id,
    1 + ((o.order_id + item_no * 3) % 14) AS product_id,
    1 + ((o.order_id + item_no) % 5) AS quantity,
    p.list_price,
    CASE
        WHEN o.customer_id % 10 = 0 THEN 0.1500
        WHEN o.customer_id % 5 = 0 THEN 0.1000
        WHEN o.order_id % 7 = 0 THEN 0.0500
        ELSE 0.0000
    END AS discount_rate
FROM public.orders AS o
CROSS JOIN generate_series(1, 1 + (o.order_id % 3)) AS item_no
JOIN public.products AS p
    ON p.product_id = 1 + ((o.order_id + item_no * 3) % 14);

INSERT INTO public.payments (order_id, paid_at, payment_method, amount)
SELECT
    o.order_id,
    o.order_date::timestamp + INTERVAL '1 day' + ((o.order_id % 8) * INTERVAL '1 hour') AS paid_at,
    (ARRAY['card', 'bank_transfer', 'cash', 'points'])[1 + (o.order_id % 4)] AS payment_method,
    SUM(oi.line_amount) AS amount
FROM public.orders AS o
JOIN public.order_items AS oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY o.order_id, o.order_date;

ANALYZE public.customers;
ANALYZE public.categories;
ANALYZE public.products;
ANALYZE public.orders;
ANALYZE public.order_items;
ANALYZE public.payments;

COMMIT;

SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM public.customers
UNION ALL
SELECT 'categories', COUNT(*) FROM public.categories
UNION ALL
SELECT 'products', COUNT(*) FROM public.products
UNION ALL
SELECT 'orders', COUNT(*) FROM public.orders
UNION ALL
SELECT 'order_items', COUNT(*) FROM public.order_items
UNION ALL
SELECT 'payments', COUNT(*) FROM public.payments
ORDER BY table_name;
