-- A load that produced nothing is a failure, not an empty source.
SELECT 'no rows' WHERE NOT EXISTS (SELECT 1 FROM analytics.event_activity WHERE source_id = %(source_id)s);
