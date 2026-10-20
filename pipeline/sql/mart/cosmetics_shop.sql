-- REES46 rows are already events: keep the source's event names, standardize the columns.
INSERT INTO analytics.event_activity (
  event_id, source_id, event_ts, event_date, event_name, user_id, session_id, first_seen_date,
  platform, country, region, city, item_id, item_category, item_brand, item_price, quantity,
  revenue, revenue_usd, currency, ep, up, src_table)
SELECT
  md5(concat_ws('|', event_ts, event_name, product_id, category_id, category_code, brand, price, user_id, user_session)),
  'cosmetics_shop',
  event_ts,
  (event_ts AT TIME ZONE 'UTC')::date,
  event_name,
  user_id,
  user_session,
  min((event_ts AT TIME ZONE 'UTC')::date) OVER (PARTITION BY user_id),
  'web', NULL, NULL, NULL,
  product_id,
  NULLIF(split_part(category_code, '.', 1), ''),
  brand,
  price,
  1,
  -- Non-positive prices are kept as events but carry no revenue (flagged in ep.price_flag).
  CASE WHEN event_name = 'purchase' AND price > 0 THEN price END,
  -- This source is already priced in USD; fill it during INSERT to avoid rewriting the mart.
  CASE WHEN event_name = 'purchase' AND price > 0 THEN price END,
  'USD',
  jsonb_strip_nulls(jsonb_build_object(
    'category_path', category_code,
    'category_id', category_id,
    'price_flag', CASE WHEN price IS NULL OR price <= 0 THEN 'non_positive' END)),
  '{}'::jsonb,
  'rees46_events'
FROM staging.cosmetics_shop_events;
