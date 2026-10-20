-- Fill revenue_usd for one store (%(source_id)s). USD stores copy revenue; other currencies divide by the
-- <currency> per USD rate of the event day, falling back to the latest earlier rate (weekends, holidays) up to 7 days.
UPDATE analytics.event_activity e
SET revenue_usd = CASE
    WHEN e.revenue IS NULL THEN NULL
    WHEN e.currency = 'USD' THEN e.revenue
    ELSE round(e.revenue / (
      SELECT r.rate FROM analytics.fx_rates r
      WHERE r.base = 'USD' AND r.quote = e.currency
        AND r.rate_date <= e.event_date AND r.rate_date > e.event_date - 7
      ORDER BY r.rate_date DESC LIMIT 1), 2)
  END
WHERE e.source_id = %(source_id)s
  -- Skip non-revenue events and values that are already correct (including USD).
  AND e.revenue_usd IS DISTINCT FROM CASE
    WHEN e.revenue IS NULL THEN NULL
    WHEN e.currency = 'USD' THEN e.revenue
    ELSE round(e.revenue / (
      SELECT r.rate FROM analytics.fx_rates r
      WHERE r.base = 'USD' AND r.quote = e.currency
        AND r.rate_date <= e.event_date AND r.rate_date > e.event_date - 7
      ORDER BY r.rate_date DESC LIMIT 1), 2)
  END;
