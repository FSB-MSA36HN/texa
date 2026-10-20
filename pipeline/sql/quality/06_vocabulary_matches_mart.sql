-- Every event name in the mart must be in the vocabulary the validator relies on.
SELECT DISTINCT e.event_name FROM analytics.event_activity e
WHERE e.source_id = %(source_id)s AND NOT EXISTS (
  SELECT 1 FROM analytics.vocabulary v
  WHERE v.source_id = e.source_id AND v.kind = 'event_name' AND v.value = e.event_name);
