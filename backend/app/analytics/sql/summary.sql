-- Period summary: the headline numbers of two adjacent periods.
--
-- Returns one row per period that has orders, labelled 'current' or
-- 'previous': paid revenue, paid orders, orders placed in any status,
-- refunded orders, and the customers with at least one paid order.
--
-- Parameters (half-open UTC instants, previous_start < current_start < current_end):
--   :previous_start  first instant of the previous period
--   :current_start   first instant of the current period
--   :current_end     first instant after the current period
WITH period_orders AS (
    SELECT
        CASE WHEN created_at >= :current_start THEN 'current' ELSE 'previous' END AS period,
        customer_id,
        status,
        total
    FROM orders
    WHERE created_at >= :previous_start
      AND created_at <  :current_end
)
SELECT
    period,
    coalesce(sum(total) FILTER (WHERE status = 'paid'), 0)     AS revenue,
    count(*) FILTER (WHERE status = 'paid')                    AS paid_orders,
    count(*)                                                   AS placed_orders,
    count(*) FILTER (WHERE status = 'refunded')                AS refunded_orders,
    count(DISTINCT customer_id) FILTER (WHERE status = 'paid') AS active_customers
FROM period_orders
GROUP BY period;
