-- Diagnostic fixture: synthetic rows only; never remove pre-existing source rows.
DO $$ BEGIN IF current_database() <> 'texa_benchmark' THEN RAISE EXCEPTION 'wrong database'; END IF;
IF EXISTS (SELECT 1 FROM analytics.event_activity WHERE source_id IN ('cosmetics_shop','olist_marketplace')) THEN RAISE EXCEPTION 'refusing existing cosmetics/olist rows'; END IF; END $$;
INSERT INTO analytics.event_activity (event_id,source_id,event_ts,event_date,event_name,user_id,session_id,first_seen_date,item_id,item_category,revenue,currency,ep,up,src_table) VALUES
('msv1_c1','cosmetics_shop','2019-12-01 12:00:00+00','2019-12-01','purchase','u1','s1','2019-12-01','101','skin',10,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_c2','cosmetics_shop','2019-12-01 12:00:00+00','2019-12-01','view','u2','s2','2019-12-01','102','hair',NULL,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_c3','cosmetics_shop','2019-12-02 12:00:00+00','2019-12-02','purchase','u1','s1','2019-12-02','103','skin',20,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_c4','cosmetics_shop','2019-12-02 12:00:00+00','2019-12-02','cart','u3','s3','2019-12-02','104','hair',NULL,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_c5','cosmetics_shop','2019-12-03 12:00:00+00','2019-12-03','view','u3','s4','2019-12-03','105','skin',NULL,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_c6','cosmetics_shop','2019-12-03 12:00:00+00','2019-12-03','purchase','u4','s5','2019-12-03','106','makeup',30,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_c7','cosmetics_shop','2019-12-04 12:00:00+00','2019-12-04','purchase','u2','s2','2019-12-04','107','hair',0,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_c8','cosmetics_shop','2019-12-04 12:00:00+00','2019-12-04','view','u5','s6','2019-12-04','108','makeup',NULL,'USD','{}'::jsonb,'{}'::jsonb,'multisource_v1');
INSERT INTO analytics.source_registry(source_id,label,description,currency,min_date,max_date,row_count,user_count,last_loaded_at) VALUES ('cosmetics_shop', 'Synthetic diagnostic cosmetics_shop', 'Synthetic diagnostic rows only; not a real warehouse', 'USD', '2019-12-01','2019-12-04',8,5,now());
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','event_name','event_name','cart',1,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','value','event_name','cart',1,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','event_name','event_name','purchase',4,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','value','event_name','purchase',4,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','event_name','event_name','view',3,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','value','event_name','view',3,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','column','column','session_id',8,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','column','column','item_id',8,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','column','column','item_category',8,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','column','column','revenue',4,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','value','item_category','hair',3,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','value','item_category','makeup',2,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('cosmetics_shop','value','item_category','skin',3,'2019-12-04');
INSERT INTO analytics.event_activity (event_id,source_id,event_ts,event_date,event_name,user_id,session_id,first_seen_date,item_id,item_category,revenue,currency,ep,up,src_table) VALUES
('msv1_o1','olist_marketplace','2019-12-01 12:00:00+00','2019-12-01','order_purchased','u1',NULL,'2019-12-01','101','skin',10,'BRL','{"order_id":"order-A"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o2','olist_marketplace','2019-12-01 12:00:00+00','2019-12-01','payment_made','u1',NULL,'2019-12-01',NULL,NULL,15,'BRL','{"order_id":"order-A"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o3','olist_marketplace','2019-12-01 12:00:00+00','2019-12-01','order_approved','u1',NULL,'2019-12-01',NULL,NULL,NULL,'BRL','{"order_id":"order-A"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o4','olist_marketplace','2019-12-02 12:00:00+00','2019-12-02','order_purchased','u2',NULL,'2019-12-02','102','hair',20,'BRL','{"order_id":"order-B"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o5','olist_marketplace','2019-12-02 12:00:00+00','2019-12-02','payment_made','u2',NULL,'2019-12-02',NULL,NULL,25,'BRL','{"order_id":"order-B"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o6','olist_marketplace','2019-12-03 12:00:00+00','2019-12-03','order_delivered','u1',NULL,'2019-12-03',NULL,NULL,NULL,'BRL','{"order_id":"order-A"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o7','olist_marketplace','2019-12-03 12:00:00+00','2019-12-03','order_purchased','u3',NULL,'2019-12-03','103','skin',30,'BRL','{"order_id":"order-C"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o8','olist_marketplace','2019-12-04 12:00:00+00','2019-12-04','payment_made','u3',NULL,'2019-12-04',NULL,NULL,50,'BRL','{"order_id":"order-C"}'::jsonb,'{}'::jsonb,'multisource_v1'),
('msv1_o9','olist_marketplace','2019-12-03 12:00:00+00','2019-12-03','order_purchased','u3',NULL,'2019-12-03','104','skin',10,'BRL','{"order_id":"order-C"}'::jsonb,'{}'::jsonb,'multisource_v1');
INSERT INTO analytics.source_registry(source_id,label,description,currency,min_date,max_date,row_count,user_count,last_loaded_at) VALUES ('olist_marketplace', 'Synthetic diagnostic olist_marketplace', 'Synthetic diagnostic rows only; not a real warehouse', 'BRL', '2019-12-01','2019-12-04',9,3,now());
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','event_name','event_name','order_approved',1,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','value','event_name','order_approved',1,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','event_name','event_name','order_delivered',1,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','value','event_name','order_delivered',1,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','event_name','event_name','order_purchased',4,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','value','event_name','order_purchased',4,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','event_name','event_name','payment_made',3,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','value','event_name','payment_made',3,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','column','column','item_id',4,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','column','column','item_category',4,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','column','column','revenue',7,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','value','item_category','hair',1,'2019-12-04');
INSERT INTO analytics.vocabulary(source_id,kind,field,value,event_count,last_seen) VALUES ('olist_marketplace','value','item_category','skin',3,'2019-12-04');
