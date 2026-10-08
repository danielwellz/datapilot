"""The suggested example questions, with the answers the demo model gives them.

The demo model (``FakeLLMClient``) needs no API key and answers exactly these
questions, so anyone can try Ask your data. Each answer's SQL is tested
against an independent calculation of the same result.
"""

import re
from dataclasses import dataclass

from app.ai.answer import LLMAnswer


@dataclass(frozen=True, slots=True)
class ExampleQuestion:
    question: str
    answer: LLMAnswer
    # Other phrasings the demo model also recognizes.
    variants: tuple[str, ...] = ()


EXAMPLE_QUESTIONS: tuple[ExampleQuestion, ...] = (
    ExampleQuestion(
        "What was the monthly revenue over the last 12 months?",
        LLMAnswer(
            sql="""\
SELECT date_trunc('month', created_at)::date AS month,
       round(sum(total), 2) AS revenue
FROM v_orders
WHERE status = 'paid'
  AND created_at >= date_trunc('month', now()) - interval '12 months'
  AND created_at < date_trunc('month', now())
GROUP BY month
ORDER BY month""",
            explanation="Revenue from paid orders in each of the last 12 complete months.",
            chart="line",
            assumptions=["The current month is left out because it is not complete yet."],
        ),
        variants=("Show monthly revenue for the past year", "Revenue by month, last 12 months"),
    ),
    ExampleQuestion(
        "Which 10 countries brought in the most revenue last year?",
        LLMAnswer(
            sql="""\
SELECT c.country, round(sum(o.total), 2) AS revenue
FROM v_orders o
JOIN v_customers c ON c.id = o.customer_id
WHERE o.status = 'paid'
  AND o.created_at >= date_trunc('year', now()) - interval '1 year'
  AND o.created_at < date_trunc('year', now())
GROUP BY c.country
ORDER BY revenue DESC, c.country
LIMIT 10""",
            explanation=(
                "The ten countries whose customers spent the most on paid orders last year."
            ),
            chart="bar",
            assumptions=["Last year means the previous calendar year."],
        ),
        variants=("Top 10 countries by revenue last year",),
    ),
    ExampleQuestion(
        "What are the top 10 products by revenue in the last 90 days?",
        LLMAnswer(
            sql="""\
SELECT p.name, round(sum(i.quantity * i.unit_price), 2) AS revenue
FROM v_order_items i
JOIN v_orders o ON o.id = i.order_id
JOIN v_products p ON p.id = i.product_id
WHERE o.status = 'paid'
  AND o.created_at >= now() - interval '90 days'
GROUP BY p.id, p.name
ORDER BY revenue DESC, p.name
LIMIT 10""",
            explanation=(
                "The ten products with the most revenue from paid orders in the last 90 days."
            ),
            chart="bar",
            assumptions=["Revenue is quantity times the unit price paid."],
        ),
        variants=("Top 10 products by revenue, last 90 days", "Best selling products last 90 days"),
    ),
    ExampleQuestion(
        "How many orders came from each channel this year?",
        LLMAnswer(
            sql="""\
SELECT channel, count(*) AS orders
FROM v_orders
WHERE created_at >= date_trunc('year', now())
GROUP BY channel
ORDER BY orders DESC, channel""",
            explanation="The number of orders placed through each channel since 1 January.",
            chart="bar",
            assumptions=["Counts orders in every status, including refunded and cancelled ones."],
        ),
        variants=("Orders by channel this year",),
    ),
    ExampleQuestion(
        "What is the average order value by country?",
        LLMAnswer(
            sql="""\
SELECT c.country, round(avg(o.total), 2) AS average_order_value
FROM v_orders o
JOIN v_customers c ON c.id = o.customer_id
WHERE o.status = 'paid'
GROUP BY c.country
ORDER BY average_order_value DESC, c.country""",
            explanation="The average value of a paid order for customers in each country.",
            chart="bar",
            assumptions=["Covers the whole order history.", "Only paid orders are averaged."],
        ),
        variants=("Average order value per country", "AOV by country"),
    ),
    ExampleQuestion(
        "What share of orders were refunded each month over the last year?",
        LLMAnswer(
            sql="""\
SELECT date_trunc('month', created_at)::date AS month,
       round(100.0 * count(*) FILTER (WHERE status = 'refunded') / count(*), 2)
           AS refund_rate_percent
FROM v_orders
WHERE created_at >= date_trunc('month', now()) - interval '12 months'
  AND created_at < date_trunc('month', now())
GROUP BY month
ORDER BY month""",
            explanation=(
                "The percentage of orders placed in each of the last 12 complete months "
                "that were later refunded."
            ),
            chart="line",
            assumptions=["The share is of all orders placed, in any status."],
        ),
        variants=("Monthly refund rate over the last year",),
    ),
    ExampleQuestion(
        "Which product categories sold the most units last quarter?",
        LLMAnswer(
            sql="""\
SELECT p.category, sum(i.quantity) AS units
FROM v_order_items i
JOIN v_orders o ON o.id = i.order_id
JOIN v_products p ON p.id = i.product_id
WHERE o.status = 'paid'
  AND o.created_at >= date_trunc('quarter', now()) - interval '3 months'
  AND o.created_at < date_trunc('quarter', now())
GROUP BY p.category
ORDER BY units DESC, p.category""",
            explanation="Units sold in paid orders for each product category last quarter.",
            chart="bar",
            assumptions=["Last quarter means the previous complete calendar quarter."],
        ),
        variants=("Units sold by category last quarter",),
    ),
    ExampleQuestion(
        "How many new customers signed up each month over the last year?",
        LLMAnswer(
            sql="""\
SELECT date_trunc('month', signed_up_at)::date AS month, count(*) AS new_customers
FROM v_customers
WHERE signed_up_at >= date_trunc('month', now()) - interval '12 months'
  AND signed_up_at < date_trunc('month', now())
GROUP BY month
ORDER BY month""",
            explanation=(
                "The number of customers who created an account in each of the last "
                "12 complete months."
            ),
            chart="line",
            assumptions=["Months without any signups are not listed."],
        ),
        variants=("New customer signups per month, last 12 months",),
    ),
)


def normalize_question(question: str) -> str:
    """Case, punctuation and spacing removed, so close spellings of a question match."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", question.lower()).split())
