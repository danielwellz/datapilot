-- Monthly revenue: paid revenue and orders per UTC calendar month, with
-- month-over-month and year-over-year change and a 3-month moving average.
--
-- Returns one row per month from :first_month to :last_month, oldest first,
-- including months without sales (revenue 0). A change is NULL when the
-- month it compares with had no revenue.
--
-- Parameters (dates on the first of a month):
--   :first_month  first month returned
--   :last_month   last month returned
WITH months AS (
    -- Twelve extra months before the first one, so that lag(12) and the
    -- moving average see real history instead of the edge of the series.
    SELECT CAST(month AS date) AS month
    FROM generate_series(
        CAST(:first_month AS date) - interval '12 months',
        CAST(:last_month AS date),
        interval '1 month'
    ) AS month
),
paid_by_month AS (
    -- AT TIME ZONE 'UTC' makes the month boundaries UTC whatever the
    -- session's time zone is.
    SELECT
        CAST(date_trunc('month', created_at AT TIME ZONE 'UTC') AS date) AS month,
        sum(total) AS revenue,
        count(*)   AS orders
    FROM orders
    WHERE status = 'paid'
      AND created_at >= (CAST(:first_month AS date) - interval '12 months') AT TIME ZONE 'UTC'
      AND created_at <  (CAST(:last_month AS date) + interval '1 month') AT TIME ZONE 'UTC'
    GROUP BY 1
),
series AS (
    SELECT
        m.month,
        coalesce(p.revenue, 0) AS revenue,
        coalesce(p.orders, 0)  AS orders
    FROM months AS m
    LEFT JOIN paid_by_month AS p USING (month)
),
compared AS (
    SELECT
        month,
        revenue,
        orders,
        lag(revenue, 1)  OVER by_month AS revenue_month_before,
        lag(revenue, 12) OVER by_month AS revenue_year_before,
        avg(revenue) OVER (by_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS moving_average
    FROM series
    WINDOW by_month AS (ORDER BY month)
)
SELECT
    month,
    revenue,
    orders,
    round((revenue - revenue_month_before) / nullif(revenue_month_before, 0), 4)
        AS revenue_change_mom,
    round((revenue - revenue_year_before) / nullif(revenue_year_before, 0), 4)
        AS revenue_change_yoy,
    round(moving_average, 2) AS revenue_moving_average_3m
FROM compared
WHERE month >= :first_month
ORDER BY month;
