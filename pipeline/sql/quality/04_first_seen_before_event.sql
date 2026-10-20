SELECT event_id, first_seen_date, event_date FROM analytics.event_activity
WHERE source_id = %(source_id)s AND first_seen_date > event_date LIMIT 5;
