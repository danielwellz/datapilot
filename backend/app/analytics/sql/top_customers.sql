-- Top customers: paid revenue per customer over a period, ranked within
-- each country.
--
-- Returns the customers whose rank in their country is :limit or better,
-- ordered by country, then rank. Customers with equal revenue share a rank
-- (dense_rank), so a country can return more than :limit customers.
--
-- Parameters:
--   :start_at  first instant of the period (UTC)
--   :end_at    first instant after the period
--   :country   ISO 3166-1 alpha-2 code, or NULL for every country
--   :limit     the worst rank returned
WITH customer_revenue AS (
    SELECT
        customer_id,
        sum(total)      AS revenue,
        count(*)        AS orders,
        max(created_at) AS last_order_at
    FROM orders
    WHERE status = 'paid'
      AND created_at >= :start_at
      AND created_at <  :end_at
    GROUP BY customer_id
),
ranked AS (
    SELECT
        c.country,
        dense_rank() OVER (PARTITION BY c.country ORDER BY r.revenue DESC) AS rank,
        c.id AS customer_id,
        c.name,
        r.revenue,
        r.orders,
        r.last_order_at
    FROM customer_revenue AS r
    JOIN customers AS c ON c.id = r.customer_id
    WHERE CAST(:country AS text) IS NULL
       OR c.country = :country
)
SELECT country, rank, customer_id, name, revenue, orders, last_order_at
FROM ranked
WHERE rank <= :limit
ORDER BY country, rank, customer_id;
