SELECT event_id, revenue FROM analytics.event_activity
WHERE source_id = %(source_id)s AND revenue < 0 LIMIT 5;
