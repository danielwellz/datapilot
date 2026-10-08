from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session, scoped_session, selectinload

from app.models import Order, OrderItem, OrderStatus, Product
from tests.factories import create_customer, create_order, create_product


@pytest.fixture
def session(db_session: scoped_session[Session]) -> Session:
    return db_session()


def test_order_round_trips_with_its_items_and_exact_money(session: Session) -> None:
    customer = create_customer()
    bottle = create_product(price="19.90")
    lamp = create_product(name="Desk Lamp", category="Home", price="45.05")
    order_id = create_order(customer, [(bottle, 3), (lamp, 1)]).id
    session.expunge_all()

    loaded = session.scalars(
        select(Order).where(Order.id == order_id).options(selectinload(Order.items))
    ).one()

    assert loaded.total == Decimal("104.75")
    assert sorted((item.quantity, item.unit_price) for item in loaded.items) == [
        (1, Decimal("45.05")),
        (3, Decimal("19.90")),
    ]
    assert loaded.created_at.tzinfo is not None


def test_relationships_refuse_to_lazy_load(session: Session) -> None:
    order_id = create_order(create_customer(), [(create_product(), 1)]).id
    session.expunge_all()
    loaded = session.get_one(Order, order_id)

    with pytest.raises(InvalidRequestError, match="lazy='raise'"):
        _ = loaded.items


def test_sales_tables_have_no_indexes_beyond_keys_and_unique_constraints(
    session: Session,
) -> None:
    # Stage 4 measures query plans before adding indexes; an index slipped in
    # here would make the "before" numbers meaningless.
    names = session.scalars(
        text(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename IN "
            "('customers', 'products', 'orders', 'order_items') ORDER BY indexname"
        )
    ).all()

    assert names == [
        "pk_customers",
        "pk_order_items",
        "pk_orders",
        "pk_products",
        "uq_customers_email",
    ]


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("status", "shipped", "ck_orders_status_allowed"),
        ("channel", "phone", "ck_orders_channel_allowed"),
        ("total", Decimal("-0.01"), "ck_orders_total_non_negative"),
        ("customer_id", 987_654_321, "fk_orders_customer_id_customers"),
    ],
)
def test_database_rejects_invalid_orders(
    session: Session, column: str, value: object, constraint: str
) -> None:
    order = create_order(create_customer(), [(create_product(), 1)])
    setattr(order, column, value)

    with pytest.raises(IntegrityError, match=constraint):
        session.flush()


@pytest.mark.parametrize(
    ("quantity", "unit_price", "constraint"),
    [
        (0, Decimal("1.00"), "ck_order_items_quantity_positive"),
        (1, Decimal("-1.00"), "ck_order_items_unit_price_non_negative"),
    ],
)
def test_database_rejects_invalid_order_items(
    session: Session, quantity: int, unit_price: Decimal, constraint: str
) -> None:
    order = create_order(create_customer(), [])
    session.add(
        OrderItem(
            order_id=order.id,
            product_id=create_product().id,
            quantity=quantity,
            unit_price=unit_price,
        )
    )

    with pytest.raises(IntegrityError, match=constraint):
        session.flush()


def test_an_order_cannot_list_the_same_product_twice(session: Session) -> None:
    product = create_product()
    order = create_order(create_customer(), [(product, 1)])
    session.add(OrderItem(order_id=order.id, product_id=product.id, quantity=2, unit_price=1))

    with pytest.raises(IntegrityError, match="pk_order_items"):
        session.flush()


def test_database_rejects_a_negative_product_price(session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_products_price_non_negative"):
        create_product(price="-0.01")


@pytest.mark.parametrize("country", ["us", "U1", "1A"])
def test_database_rejects_a_country_that_is_not_an_uppercase_iso_code(country: str) -> None:
    with pytest.raises(IntegrityError, match="ck_customers_country_iso_alpha2"):
        create_customer(country=country)


def test_database_rejects_a_duplicate_customer_email() -> None:
    create_customer(email="mia@example.com")

    with pytest.raises(IntegrityError, match="uq_customers_email"):
        create_customer(email="mia@example.com")


def test_deleting_an_order_deletes_its_items(session: Session) -> None:
    order = create_order(create_customer(), [(create_product(), 1)])

    session.execute(delete(Order).where(Order.id == order.id))

    assert session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all() == []


def test_a_product_with_order_history_cannot_be_deleted(session: Session) -> None:
    product = create_product()
    create_order(create_customer(), [(product, 1)])

    with pytest.raises(IntegrityError, match="fk_order_items_product_id_products"):
        session.execute(delete(Product).where(Product.id == product.id))


def test_reprs_identify_rows_without_personal_data(session: Session) -> None:
    customer = create_customer(email="mia@example.com", name="Mia Novak")
    product = create_product(name="Desk Lamp")
    order = create_order(customer, [(product, 1)], status=OrderStatus.REFUNDED)
    item = session.get_one(OrderItem, (order.id, product.id))

    assert "mia@example.com" not in repr(customer)
    assert "Mia Novak" not in repr(customer)
    assert repr(product) == f"Product(id={product.id}, name='Desk Lamp')"
    assert "status='refunded'" in repr(order)
    assert repr(item) == f"OrderItem(order_id={order.id}, product_id={product.id})"
    assert repr(customer) == f"Customer(id={customer.id}, country='US')"
