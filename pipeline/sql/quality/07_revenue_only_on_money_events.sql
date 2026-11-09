-- Revenue may only sit on money events (shop purchase, Olist item purchase, Olist payment).
-- A lifecycle row (shipped, delivered, review...) carrying revenue would be double counted by any raw sum.
SELECT event_name, count(*) FROM analytics.event_activity
WHERE source_id = %(source_id)s AND revenue IS NOT NULL
  AND event_name NOT IN ('purchase', 'order_purchased', 'payment_made')
GROUP BY event_name LIMIT 5;
