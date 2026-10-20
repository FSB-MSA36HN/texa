-- Typed, cleaned REES46 events. Exact duplicate rows are dropped; rows without user or time are dropped.
CREATE TEMP TABLE IF NOT EXISTS stage_log (step text, rows_in bigint, rows_out bigint, note text);

DROP TABLE IF EXISTS staging.cosmetics_shop_events;
CREATE TABLE staging.cosmetics_shop_events AS
SELECT DISTINCT
  analytics.try_timestamptz(event_time)  AS event_ts,
  NULLIF(btrim(event_type), '')          AS event_name,
  NULLIF(btrim(product_id), '')          AS product_id,
  NULLIF(btrim(category_id), '')         AS category_id,
  NULLIF(btrim(category_code), '')       AS category_code,
  NULLIF(btrim(brand), '')               AS brand,
  analytics.try_numeric(price)           AS price,
  NULLIF(btrim(user_id), '')             AS user_id,
  NULLIF(btrim(user_session), '')        AS user_session
FROM raw.cosmetics_shop__events;

INSERT INTO stage_log SELECT 'events', (SELECT count(*) FROM raw.cosmetics_shop__events), count(*), 'after distinct'
FROM staging.cosmetics_shop_events;

DELETE FROM staging.cosmetics_shop_events WHERE event_ts IS NULL OR user_id IS NULL OR event_name IS NULL;

INSERT INTO stage_log SELECT 'events_required_fields', (SELECT rows_out FROM stage_log WHERE step = 'events'), count(*),
  'dropped rows missing time, user or event'
FROM staging.cosmetics_shop_events;
