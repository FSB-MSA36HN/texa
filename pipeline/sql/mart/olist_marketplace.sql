-- Olist is relational: each business step becomes an event row. Names stay source-specific
-- (order_purchased, not purchase); the semantic catalog maps them to business roles.
INSERT INTO analytics.event_activity (
  event_id, source_id, event_ts, event_date, event_name, user_id, session_id, first_seen_date,
  platform, country, region, city, item_id, item_category, item_brand, item_price, quantity,
  revenue, revenue_usd, currency, ep, up, src_table)
WITH orders AS (
  SELECT o.*, c.customer_unique_id AS user_id, c.city, c.state, c.zip_prefix,
         p.payment_type AS main_payment_type
  FROM staging.olist_orders o
  JOIN staging.olist_customers c USING (customer_id)
  LEFT JOIN staging.olist_payments p ON p.order_id = o.order_id AND p.payment_sequential = 1
),
events AS (
  -- One purchase event per order item, so revenue and item attributes line up like a shop event stream.
  SELECT md5('item|' || i.order_id || '|' || i.order_item_id) AS event_id, o.purchased_at AS event_ts,
         'order_purchased' AS event_name, o.user_id, o.city, o.state, o.zip_prefix,
         i.product_id AS item_id, pr.category AS item_category, i.price AS item_price, 1 AS quantity,
         CASE WHEN i.price > 0 THEN i.price END AS revenue,
         jsonb_build_object('order_id', o.order_id, 'order_item_id', i.order_item_id::text,
           'freight_value', i.freight_value::text, 'seller_id', i.seller_id, 'seller_state', s.state,
           'order_status', o.order_status, 'payment_type', o.main_payment_type) AS ep,
         'order_items' AS src_table
  FROM staging.olist_order_items i
  JOIN orders o USING (order_id)
  LEFT JOIN staging.olist_products pr USING (product_id)
  LEFT JOIN staging.olist_sellers s USING (seller_id)
  UNION ALL
  SELECT md5('approved|' || order_id), approved_at, 'order_approved', user_id, city, state, zip_prefix,
         NULL, NULL, NULL, NULL, NULL,
         jsonb_build_object('order_id', order_id, 'payment_type', main_payment_type), 'orders'
  FROM orders WHERE approved_at IS NOT NULL
  UNION ALL
  SELECT md5('shipped|' || order_id), shipped_at, 'order_shipped', user_id, city, state, zip_prefix,
         NULL, NULL, NULL, NULL, NULL,
         jsonb_build_object('order_id', order_id), 'orders'
  FROM orders WHERE shipped_at IS NOT NULL
  UNION ALL
  SELECT md5('delivered|' || order_id), delivered_at, 'order_delivered', user_id, city, state, zip_prefix,
         NULL, NULL, NULL, NULL, NULL,
         jsonb_build_object('order_id', order_id,
           'delivery_days', round(extract(epoch FROM delivered_at - purchased_at) / 86400.0, 1)::text,
           'is_late', CASE WHEN estimated_at IS NULL THEN NULL WHEN delivered_at::date > estimated_at::date THEN 'true' ELSE 'false' END),
         'orders'
  FROM orders WHERE delivered_at IS NOT NULL
  UNION ALL
  -- Olist has no cancellation time; the event is dated at purchase (ep.dated_by says so).
  SELECT md5('canceled|' || order_id), purchased_at, 'order_canceled', user_id, city, state, zip_prefix,
         NULL, NULL, NULL, NULL, NULL,
         jsonb_build_object('order_id', order_id, 'dated_by', 'order_purchase'), 'orders'
  FROM orders WHERE order_status = 'canceled'
  UNION ALL
  SELECT md5('payment|' || p.order_id || '|' || p.payment_sequential), o.purchased_at, 'payment_made',
         o.user_id, o.city, o.state, o.zip_prefix, NULL, NULL, NULL, NULL,
         CASE WHEN p.payment_value > 0 THEN p.payment_value END,
         jsonb_build_object('order_id', p.order_id, 'payment_type', p.payment_type,
           'installments', p.installments::text, 'payment_sequential', p.payment_sequential::text),
         'payments'
  FROM staging.olist_payments p JOIN orders o USING (order_id)
  UNION ALL
  SELECT md5('review|' || r.review_id || '|' || r.order_id), r.reviewed_at, 'review_submitted',
         o.user_id, o.city, o.state, o.zip_prefix, NULL, NULL, NULL, NULL, NULL,
         jsonb_build_object('order_id', r.order_id, 'review_id', r.review_id, 'review_score', r.review_score::text),
         'reviews'
  FROM staging.olist_reviews r JOIN orders o USING (order_id)
)
SELECT
  event_id, 'olist_marketplace', event_ts, (event_ts AT TIME ZONE 'UTC')::date, event_name, user_id, NULL,
  min((event_ts AT TIME ZONE 'UTC')::date) OVER (PARTITION BY user_id),
  'web', 'BR', state, city, item_id, item_category, NULL, item_price, quantity,
  revenue,
  CASE WHEN revenue IS NOT NULL THEN round(revenue / (
    SELECT r.rate FROM analytics.fx_rates r
    WHERE r.base = 'USD' AND r.quote = 'BRL'
      AND r.rate_date <= (event_ts AT TIME ZONE 'UTC')::date
      AND r.rate_date > (event_ts AT TIME ZONE 'UTC')::date - 7
    ORDER BY r.rate_date DESC LIMIT 1), 2) END,
  'BRL', jsonb_strip_nulls(ep),
  jsonb_strip_nulls(jsonb_build_object('customer_state', state, 'customer_zip_prefix', zip_prefix)),
  src_table
FROM events;
