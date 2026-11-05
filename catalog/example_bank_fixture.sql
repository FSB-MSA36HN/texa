-- Tiny deterministic semantic fixture for independently checking authored
-- reference SQL. Run inside a transaction against the isolated texa_benchmark
-- database; ROLLBACK afterwards. Verification remaps only the qualified table
-- from analytics.event_activity to example_review.event_activity.
CREATE SCHEMA example_review;
CREATE TABLE example_review.event_activity (
    event_date date NOT NULL,
    event_name text NOT NULL,
    user_id text,
    session_id text,
    item_category text,
    revenue numeric,
    source_id text NOT NULL
);

INSERT INTO example_review.event_activity VALUES
    ('2026-01-03', 'view', 'c1', 'cs1', 'skin', 0, 'cosmetics_shop'),
    ('2026-01-04', 'view', 'c2', 'cs2', 'hair', 0, 'cosmetics_shop'),
    ('2026-01-05', 'purchase', 'c1', 'cs1', 'skin', 10, 'cosmetics_shop'),
    ('2026-01-06', 'purchase', 'c2', 'cs2', 'hair', 5, 'cosmetics_shop'),
    ('2026-02-02', 'view', 'c3', 'cs3', 'skin', 0, 'cosmetics_shop'),
    ('2026-02-03', 'purchase', 'c3', 'cs3', 'skin', 0, 'cosmetics_shop'),
    ('2026-01-11', 'order_purchased', 'o1', 'os1', 'skin', 100, 'olist_marketplace'),
    ('2026-01-11', 'order_purchased', 'o1', 'os1', 'skin', 25, 'olist_marketplace'),
    ('2026-02-12', 'order_purchased', 'o2', 'os2', NULL, 20, 'olist_marketplace'),
    ('2026-02-12', 'payment_made', 'o1', 'os1', NULL, 999, 'olist_marketplace'),
    ('2026-02-13', 'order_approved', 'o3', 'os3', 'home', 0, 'olist_marketplace');
