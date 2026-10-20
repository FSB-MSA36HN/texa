-- One currency per source; mixing would make revenue sums meaningless.
SELECT count(DISTINCT currency) FROM analytics.event_activity
WHERE source_id = %(source_id)s HAVING count(DISTINCT currency) > 1;
