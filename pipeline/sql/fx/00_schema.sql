-- Daily exchange rates and the converted revenue column. Safe to run again: the init script only runs on an empty
-- volume, so the ETL applies this to warehouses created before it existed.
CREATE TABLE IF NOT EXISTS analytics.fx_rates (
  rate_date date    NOT NULL,
  base      text    NOT NULL,   -- e.g. USD
  quote     text    NOT NULL,   -- e.g. BRL
  rate      numeric NOT NULL CHECK (rate > 0),   -- 1 base = rate quote (FRED DEXBZUS: BRL per 1 USD)
  source    text    NOT NULL,
  PRIMARY KEY (base, quote, rate_date)
);

-- Revenue in USD at the rate of the event's own day (or the last trading day before it). NULL when no rate covers
-- the day, so Texa reports "cannot compute" rather than a wrong 0.
ALTER TABLE analytics.event_activity ADD COLUMN IF NOT EXISTS revenue_usd numeric(14,2);

GRANT SELECT ON analytics.fx_rates TO texa_reader;
