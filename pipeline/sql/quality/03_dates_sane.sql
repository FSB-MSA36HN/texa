SELECT event_id, event_date FROM analytics.event_activity
WHERE source_id = %(source_id)s AND (event_date < DATE '2000-01-01' OR event_date > current_date) LIMIT 5;
