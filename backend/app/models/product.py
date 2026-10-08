"""Products in the store's catalog."""

from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, Identity, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import Base

PRODUCT_NAME_MAX_LENGTH = 120
CATEGORY_MAX_LENGTH = 50


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("price >= 0", name="price_non_negative"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(PRODUCT_NAME_MAX_LENGTH))
    category: Mapped[str] = mapped_column(String(CATEGORY_MAX_LENGTH))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    def __repr__(self) -> str:
        return f"Product(id={self.id!r}, name={self.name!r})"
