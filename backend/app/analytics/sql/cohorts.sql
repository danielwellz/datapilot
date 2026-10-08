-- Retention cohorts: customers grouped by the UTC month they signed up, and
-- for each month since signup, the share of the cohort with a paid order.
--
-- Returns one row per cohort and month since signup (0 is the signup month
-- itself), up to :last_month, ordered by cohort and month. Months in which
-- nobody ordered are included with zero. Months without signups have no
-- cohort and no rows.
--
-- Parameters (dates on the first of a month):
--   :first_month  the oldest cohort
--   :last_month   the newest cohort, and the last month of activity counted
WITH cohort_members AS (
    SELECT
        id AS customer_id,
        CAST(date_trunc('month', signed_up_at AT TIME ZONE 'UTC') AS date) AS cohort_month
    FROM customers
    WHERE signed_up_at >= CAST(:first_month AS timestamp) AT TIME ZONE 'UTC'
      AND signed_up_at <  (CAST(:last_month AS date) + interval '1 month') AT TIME ZONE 'UTC'
),
cohort_sizes AS (
    SELECT cohort_month, count(*) AS customers
    FROM cohort_members
    GROUP BY cohort_month
),
active_members AS (
    -- Each member at most once per month, however many orders they placed.
    -- Only customer_id, created_at and status are read from orders, so the
    -- partial index ix_orders_paid_customer_id_created_at answers the join
    -- on its own; reading another order column would lose that.
    SELECT DISTINCT
        m.cohort_month,
        m.customer_id,
        CAST(date_trunc('month', o.created_at AT TIME ZONE 'UTC') AS date) AS active_month
    FROM cohort_members AS m
    JOIN orders AS o ON o.customer_id = m.customer_id
    WHERE o.status = 'paid'
      AND o.created_at >= CAST(:first_month AS timestamp) AT TIME ZONE 'UTC'
      AND o.created_at <  (CAST(:last_month AS date) + interval '1 month') AT TIME ZONE 'UTC'
),
monthly_activity AS (
    SELECT cohort_month, active_month, count(*) AS active_customers
    FROM active_members
    GROUP BY cohort_month, active_month
),
grid AS (
    -- Every month from each cohort's signup month to :last_month, so months
    -- without activity still appear.
    SELECT
        s.cohort_month,
        s.customers,
        CAST(month AS date) AS active_month
    FROM cohort_sizes AS s
    CROSS JOIN LATERAL generate_series(
        s.cohort_month, CAST(:last_month AS date), interval '1 month'
    ) AS month
)
SELECT
    g.cohort_month,
    g.customers,
    CAST(
        row_number() OVER (PARTITION BY g.cohort_month ORDER BY g.active_month) - 1 AS integer
    ) AS months_since_signup,
    coalesce(a.active_customers, 0) AS active_customers,
    round(coalesce(a.active_customers, 0) / CAST(g.customers AS numeric), 4) AS retention_rate
FROM grid AS g
LEFT JOIN monthly_activity AS a USING (cohort_month, active_month)
ORDER BY g.cohort_month, g.active_month;
