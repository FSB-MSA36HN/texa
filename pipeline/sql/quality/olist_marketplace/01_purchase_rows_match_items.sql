-- One order_purchased row per order item whose order has a customer record.
-- A mismatch means items were lost or duplicated between staging and the mart.
SELECT mart.n AS mart_rows, staged.n AS staged_items
FROM (SELECT count(*) AS n FROM analytics.event_activity
      WHERE source_id = %(source_id)s AND event_name = 'order_purchased') mart,
     (SELECT count(*) AS n FROM staging.olist_order_items i
      JOIN staging.olist_orders o USING (order_id)
      JOIN staging.olist_customers c USING (customer_id)) staged
WHERE mart.n <> staged.n;
