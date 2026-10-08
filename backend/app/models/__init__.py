"""SQLAlchemy models.

Every model is imported here so that ``db.metadata`` is complete whenever the
application is built, which Alembic autogenerate relies on.
"""

from app.models.customer import Customer
from app.models.order import Order, OrderChannel, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User

__all__ = [
    "Customer",
    "Order",
    "OrderChannel",
    "OrderItem",
    "OrderStatus",
    "Product",
    "User",
]
