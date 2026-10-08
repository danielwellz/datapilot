-- Product ranking: paid revenue and units sold per product over a period,
-- ranked by revenue, with each product's share of its category's revenue.
--
-- Returns the products ranked :limit or better, best first. Equal revenue
-- shares a rank (dense_rank), so more than :limit products can be returned.
-- With :category the ranking is within that category. Shares are computed
-- before the limit, so they are shares of the whole category.
--
-- Parameters:
--   :start_at  first instant of the period (UTC)
--   :end_at    first instant after the period
--   :category  a category name, or NULL for every category
--   :limit     the worst rank returned
WITH product_sales AS (
    SELECT
        i.product_id,
        sum(i.quantity * i.unit_price) AS revenue,
        sum(i.quantity)                AS units
    FROM order_items AS i
    JOIN orders AS o ON o.id = i.order_id
    WHERE o.status = 'paid'
      AND o.created_at >= :start_at
      AND o.created_at <  :end_at
    GROUP BY i.product_id
),
ranked AS (
    SELECT
        dense_rank() OVER (ORDER BY s.revenue DESC) AS rank,
        p.id AS product_id,
        p.name,
        p.category,
        s.revenue,
        s.units,
        s.revenue / nullif(sum(s.revenue) OVER (PARTITION BY p.category), 0) AS category_share
    FROM product_sales AS s
    JOIN products AS p ON p.id = s.product_id
    WHERE CAST(:category AS text) IS NULL
       OR p.category = :category
)
SELECT
    rank,
    product_id,
    name,
    category,
    revenue,
    units,
    round(category_share, 4) AS category_share
FROM ranked
WHERE rank <= :limit
ORDER BY rank, product_id;
