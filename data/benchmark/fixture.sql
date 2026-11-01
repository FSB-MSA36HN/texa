-- Apply only to a dedicated `texa_benchmark` database based on the existing app schema.
-- Idempotently replace rows from this benchmark source; other source partitions are untouched.
CREATE TABLE IF NOT EXISTS analytics.event_activity_event_benchmark
  PARTITION OF analytics.event_activity FOR VALUES IN ('event_benchmark');

DELETE FROM analytics.event_activity WHERE source_id = 'event_benchmark';
INSERT INTO analytics.event_activity
  (event_id, source_id, event_ts, event_date, event_name, user_id, session_id,
   first_seen_date, platform, item_id, item_category, item_price, quantity, revenue,
   currency, ep, up, src_table)
VALUES
('e01','event_benchmark','2025-01-01 09:00+00','2025-01-01','view','u1','s1','2025-01-01','web','p1','shoes',40,1,NULL,'USD','{"device":{"type":"mobile"},"campaign":{"channel":"paid"},"product":{"category":"shoes"}}','{}','pilot'),
('e02','event_benchmark','2025-01-01 09:05+00','2025-01-01','cart','u1','s1','2025-01-01','web','p1','shoes',40,1,NULL,'USD','{"device":{"type":"mobile"},"campaign":{"channel":"paid"},"product":{"category":"shoes"}}','{}','pilot'),
('e03','event_benchmark','2025-01-01 09:10+00','2025-01-01','purchase','u1','s1','2025-01-01','web','p1','shoes',40,1,40,'USD','{"device":{"type":"mobile"},"campaign":{"channel":"paid"},"product":{"category":"shoes"},"checkout":{"amount":"40"}}','{}','pilot'),
('e04','event_benchmark','2025-01-01 11:00+00','2025-01-01','view','u2','s2','2025-01-01','ios','p2','books',20,1,NULL,'USD','{"device":{"type":"mobile"},"campaign":{"channel":"organic"},"product":{"category":"books"}}','{}','pilot'),
('e05','event_benchmark','2025-01-02 08:00+00','2025-01-02','view','u3','s3','2025-01-02','web','p3','books',25,1,NULL,'USD','{"device":{"type":"desktop"},"campaign":{"channel":"organic"},"product":{"category":"books"}}','{}','pilot'),
('e06','event_benchmark','2025-01-02 08:30+00','2025-01-02','purchase','u3','s3','2025-01-02','web','p3','books',25,1,25,'USD','{"device":{"type":"desktop"},"campaign":{"channel":"organic"},"product":{"category":"books"},"checkout":{"amount":"25"}}','{}','pilot'),
('e07','event_benchmark','2025-01-02 10:00+00','2025-01-02','view','u1','s4','2025-01-01','android','p4','shoes',60,1,NULL,'USD','{"device":{"type":"mobile"},"campaign":{"channel":"email"},"product":{"category":"shoes"}}','{}','pilot'),
('e08','event_benchmark','2025-01-02 10:05+00','2025-01-02','purchase','u1','s4','2025-01-01','android','p4','shoes',60,1,60,'USD','{"device":{"type":"mobile"},"campaign":{"channel":"email"},"product":{"category":"shoes"},"checkout":{"amount":"60"}}','{}','pilot'),
('e09','event_benchmark','2025-01-03 12:00+00','2025-01-03','view','u4','s5','2025-01-03','ios','p5','toys',10,1,NULL,'USD','{"device":{"type":"tablet"},"campaign":{"channel":"paid"},"product":{"category":"toys"}}','{}','pilot'),
('e10','event_benchmark','2025-01-03 12:05+00','2025-01-03','cart','u4','s5','2025-01-03','ios','p5','toys',10,1,NULL,'USD','{"device":{"type":"tablet"},"campaign":{"channel":"paid"},"product":{"category":"toys"}}','{}','pilot'),
('e11','event_benchmark','2025-01-03 12:10+00','2025-01-03','purchase','u4','s5','2025-01-03','ios','p5','toys',10,1,10,'USD','{"device":{"type":"tablet"},"campaign":{"channel":"paid"},"product":{"category":"toys"},"checkout":{"amount":"10"}}','{}','pilot'),
('e12','event_benchmark','2025-01-03 15:00+00','2025-01-03','view','u5','s6','2025-01-03','web','p6','shoes',30,1,NULL,'USD','{"device":{"type":"desktop"},"campaign":{"channel":"referral"},"product":{"category":"shoes"}}','{}','pilot');

INSERT INTO analytics.source_registry
  (source_id, label, description, currency, min_date, max_date, row_count, user_count, last_loaded_at)
VALUES ('event_benchmark', 'Synthetic product events pilot', 'Frozen 12-row benchmark fixture',
        'USD', '2025-01-01', '2025-01-03', 12, 5, now())
ON CONFLICT (source_id) DO UPDATE SET label=EXCLUDED.label, description=EXCLUDED.description,
  currency=EXCLUDED.currency, min_date=EXCLUDED.min_date, max_date=EXCLUDED.max_date,
  row_count=EXCLUDED.row_count, user_count=EXCLUDED.user_count, last_loaded_at=EXCLUDED.last_loaded_at;

DELETE FROM analytics.vocabulary WHERE source_id='event_benchmark';
INSERT INTO analytics.vocabulary (source_id, kind, field, value, event_count, last_seen)
SELECT source_id, 'event_name', 'event_name', event_name, count(*), max(event_date)
FROM analytics.event_activity WHERE source_id='event_benchmark' GROUP BY source_id, event_name;
INSERT INTO analytics.vocabulary (source_id, kind, field, value, event_count, last_seen)
SELECT 'event_benchmark', 'ep_key', 'ep', key, 12, '2025-01-03'::date
FROM (VALUES ('device.type'), ('campaign.channel'), ('product.category'), ('checkout.amount')) AS paths(key);
INSERT INTO analytics.vocabulary (source_id, kind, field, value, event_count, last_seen)
SELECT 'event_benchmark', 'column', 'column', column_name, 12, '2025-01-03'::date
FROM (VALUES ('event_date'), ('event_name'), ('user_id'), ('session_id'), ('item_category'), ('revenue')) AS cols(column_name);
