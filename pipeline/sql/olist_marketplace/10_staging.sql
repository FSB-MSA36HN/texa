-- Typed Olist tables. Timestamps are local marketplace time without zone; stored as UTC as-is.
CREATE TEMP TABLE IF NOT EXISTS stage_log (step text, rows_in bigint, rows_out bigint, note text);

DROP TABLE IF EXISTS staging.olist_customers;
CREATE TABLE staging.olist_customers AS
SELECT DISTINCT ON (customer_id)
  customer_id, customer_unique_id, NULLIF(customer_zip_code_prefix, '') AS zip_prefix,
  initcap(NULLIF(btrim(customer_city), '')) AS city, upper(NULLIF(btrim(customer_state), '')) AS state
FROM raw.olist_marketplace__customers
WHERE customer_id <> '' AND customer_unique_id <> '';
INSERT INTO stage_log SELECT 'customers', (SELECT count(*) FROM raw.olist_marketplace__customers), count(*), NULL FROM staging.olist_customers;

DROP TABLE IF EXISTS staging.olist_orders;
CREATE TABLE staging.olist_orders AS
SELECT DISTINCT ON (o.order_id)
  o.order_id, o.customer_id, o.order_status,
  analytics.try_timestamptz(o.order_purchase_timestamp || '+00')       AS purchased_at,
  analytics.try_timestamptz(o.order_approved_at || '+00')              AS approved_at,
  analytics.try_timestamptz(o.order_delivered_carrier_date || '+00')   AS shipped_at,
  analytics.try_timestamptz(o.order_delivered_customer_date || '+00')  AS delivered_at,
  analytics.try_timestamptz(o.order_estimated_delivery_date || '+00')  AS estimated_at
FROM raw.olist_marketplace__orders o
WHERE o.order_id <> '';
DELETE FROM staging.olist_orders WHERE purchased_at IS NULL;
INSERT INTO stage_log SELECT 'orders', (SELECT count(*) FROM raw.olist_marketplace__orders), count(*), 'dropped orders without purchase time' FROM staging.olist_orders;

DROP TABLE IF EXISTS staging.olist_products;
CREATE TABLE staging.olist_products AS
SELECT DISTINCT ON (p.product_id)
  p.product_id,
  COALESCE(t.product_category_name_english, NULLIF(p.product_category_name, '')) AS category
FROM raw.olist_marketplace__products p
LEFT JOIN raw.olist_marketplace__category_translation t ON t.product_category_name = p.product_category_name;

DROP TABLE IF EXISTS staging.olist_sellers;
CREATE TABLE staging.olist_sellers AS
SELECT DISTINCT ON (seller_id) seller_id, upper(NULLIF(seller_state, '')) AS state
FROM raw.olist_marketplace__sellers;

DROP TABLE IF EXISTS staging.olist_order_items;
CREATE TABLE staging.olist_order_items AS
SELECT DISTINCT
  order_id, order_item_id::int AS order_item_id, product_id, seller_id,
  analytics.try_numeric(price) AS price, analytics.try_numeric(freight_value) AS freight_value
FROM raw.olist_marketplace__order_items;
INSERT INTO stage_log SELECT 'order_items', (SELECT count(*) FROM raw.olist_marketplace__order_items), count(*), NULL FROM staging.olist_order_items;

DROP TABLE IF EXISTS staging.olist_payments;
CREATE TABLE staging.olist_payments AS
SELECT DISTINCT
  order_id, payment_sequential::int AS payment_sequential, NULLIF(payment_type, '') AS payment_type,
  analytics.try_numeric(payment_installments)::int AS installments, analytics.try_numeric(payment_value) AS payment_value
FROM raw.olist_marketplace__payments;
INSERT INTO stage_log SELECT 'payments', (SELECT count(*) FROM raw.olist_marketplace__payments), count(*), NULL FROM staging.olist_payments;

DROP TABLE IF EXISTS staging.olist_reviews;
CREATE TABLE staging.olist_reviews AS
SELECT DISTINCT ON (review_id, order_id)
  review_id, order_id, analytics.try_numeric(review_score)::int AS review_score,
  analytics.try_timestamptz(review_creation_date || '+00') AS reviewed_at
FROM raw.olist_marketplace__reviews
WHERE review_id <> '';
DELETE FROM staging.olist_reviews WHERE reviewed_at IS NULL;
INSERT INTO stage_log SELECT 'reviews', (SELECT count(*) FROM raw.olist_marketplace__reviews), count(*), 'dropped reviews without date' FROM staging.olist_reviews;
