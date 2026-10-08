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
WITH customer_periods AS (
    -- One row per customer and period. Counting these rows replaces
    -- count(DISTINCT customer_id), which sorts every order in the range in
    -- a single process; this GROUP BY is split across parallel workers.
    -- The key is a boolean rather than the period label because a
    -- condition on a bind parameter keeps the plan parallel.
    SELECT
        customer_id,
        created_at >= :current_start                AS in_current,
        sum(total) FILTER (WHERE status = 'paid')   AS revenue,
        count(*) FILTER (WHERE status = 'paid')     AS paid_orders,
        count(*)                                    AS placed_orders,
        count(*) FILTER (WHERE status = 'refunded') AS refunded_orders
    FROM orders
    WHERE created_at >= :previous_start
      AND created_at <  :current_end
    GROUP BY customer_id, in_current
)
SELECT
    CASE WHEN in_current THEN 'current' ELSE 'previous' END AS period,
    coalesce(sum(revenue), 0)               AS revenue,
    CAST(sum(paid_orders) AS bigint)        AS paid_orders,
    CAST(sum(placed_orders) AS bigint)      AS placed_orders,
    CAST(sum(refunded_orders) AS bigint)    AS refunded_orders,
    count(*) FILTER (WHERE paid_orders > 0) AS active_customers
FROM customer_periods
GROUP BY in_current;
