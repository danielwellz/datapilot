"""SQLAlchemy models.

Every model is imported here so that ``db.metadata`` is complete whenever the
application is built, which Alembic autogenerate relies on.
"""

from app.models.ai_query import AiQuery, AiQueryStatus
from app.models.customer import Customer
from app.models.order import Order, OrderChannel, OrderItem, OrderSort, OrderStatus
from app.models.product import Product
from app.models.user import User

__all__ = [
    "AiQuery",
    "AiQueryStatus",
    "Customer",
    "Order",
    "OrderChannel",
    "OrderItem",
    "OrderSort",
    "OrderStatus",
    "Product",
    "User",
]
