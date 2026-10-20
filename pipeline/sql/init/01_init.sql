-- Texa warehouse bootstrap. Runs once in the `texa` database on first container start.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS app;

-- SAFE_CAST equivalents: bad input becomes NULL instead of failing the query.
CREATE OR REPLACE FUNCTION analytics.try_numeric(v text) RETURNS numeric
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
  RETURN NULLIF(btrim(v), '')::numeric;
EXCEPTION WHEN others THEN
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION analytics.try_timestamptz(v text) RETURNS timestamptz
LANGUAGE plpgsql STABLE AS $$
BEGIN
  RETURN NULLIF(btrim(v), '')::timestamptz;
EXCEPTION WHEN others THEN
  RETURN NULL;
END $$;

-- The unified table: every source shares these columns; source-specific attributes live in ep/up.
CREATE TABLE IF NOT EXISTS analytics.event_activity (
  event_id        text        NOT NULL,
  source_id       text        NOT NULL,
  event_ts        timestamptz NOT NULL,
  event_date      date        NOT NULL,
  event_name      text        NOT NULL,
  user_id         text        NOT NULL,
  session_id      text,
  first_seen_date date        NOT NULL,
  platform        text,
  country         text,
  region          text,
  city            text,
  item_id         text,
  item_category   text,
  item_brand      text,
  item_price      numeric(14,2),
  quantity        int,
  revenue         numeric(14,2),
  currency        text,
  ep              jsonb       NOT NULL DEFAULT '{}'::jsonb,
  up              jsonb       NOT NULL DEFAULT '{}'::jsonb,
  src_table       text,
  ingested_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_id, event_id)
) PARTITION BY LIST (source_id);

CREATE TABLE IF NOT EXISTS analytics.event_activity_cosmetics_shop
  PARTITION OF analytics.event_activity FOR VALUES IN ('cosmetics_shop');
CREATE TABLE IF NOT EXISTS analytics.event_activity_olist_marketplace
  PARTITION OF analytics.event_activity FOR VALUES IN ('olist_marketplace');

CREATE INDEX IF NOT EXISTS event_activity_date_idx ON analytics.event_activity (source_id, event_date);
CREATE INDEX IF NOT EXISTS event_activity_name_idx ON analytics.event_activity (source_id, event_name, event_date);
CREATE INDEX IF NOT EXISTS event_activity_user_idx ON analytics.event_activity (source_id, user_id);

CREATE TABLE IF NOT EXISTS analytics.source_registry (
  source_id      text PRIMARY KEY,
  label          text NOT NULL,
  description    text NOT NULL DEFAULT '',
  currency       text,
  min_date       date,
  max_date       date,
  row_count      bigint,
  user_count     bigint,
  last_loaded_at timestamptz
);

-- What each source actually logs. The validator refuses events/values that never occur.
CREATE TABLE IF NOT EXISTS analytics.vocabulary (
  source_id   text NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('event_name', 'ep_key', 'up_key', 'column', 'value')),
  field       text NOT NULL,
  value       text NOT NULL,
  event_count bigint NOT NULL,
  last_seen   date,
  PRIMARY KEY (source_id, kind, field, value)
);

CREATE TABLE IF NOT EXISTS analytics.etl_runs (
  id           bigserial PRIMARY KEY,
  source_id    text NOT NULL,
  step         text NOT NULL,
  rows_in      bigint,
  rows_out     bigint,
  rows_dropped bigint,
  note         text,
  finished_at  timestamptz NOT NULL DEFAULT now()
);

-- Read-only role the API uses to run compiled SQL.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'texa_reader') THEN
    CREATE ROLE texa_reader LOGIN PASSWORD 'texa_reader';
  END IF;
END $$;
ALTER ROLE texa_reader SET default_transaction_read_only = on;
ALTER ROLE texa_reader SET statement_timeout = '30s';
GRANT USAGE ON SCHEMA analytics TO texa_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO texa_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO texa_reader;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA analytics TO texa_reader;
