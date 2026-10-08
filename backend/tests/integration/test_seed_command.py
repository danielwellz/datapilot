import itertools
from datetime import date

import pytest
from flask import Flask
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session, scoped_session

from app import clock
from app.cli import ProgressPrinter, format_seed_report, format_size
from app.models import Order, User
from app.seed import generator
from app.seed.generator import SCALES, SeedScale
from app.seed.loader import TableStats
from app.services.cache import DATA_VERSION_KEY
from app.services.passwords import PasswordHasher
from app.services.seeding import (
    DEMO_EMAIL,
    DEMO_PASSWORD,
    SeedReport,
    SeedService,
)
from tests.factories import create_user

END_DATE = date(2026, 10, 1)
TINY = SeedScale("tiny", customers=300, products=40, orders=3_000)


@pytest.fixture
def session(db_session: scoped_session[Session]) -> Session:
    return db_session()


@pytest.fixture
def service(session: Session, redis_client: Redis) -> SeedService:
    ticks = itertools.count(start=100.0, step=2.5)
    return SeedService(session, redis_client, PasswordHasher(), clock=lambda: next(ticks))


@pytest.fixture
def tiny_small_scale(monkeypatch: pytest.MonkeyPatch) -> SeedScale:
    """Make ``--scale small`` load the tiny scale, so command tests stay fast."""
    scale = SeedScale("small", TINY.customers, TINY.products, TINY.orders)
    monkeypatch.setitem(SCALES, "small", scale)
    return scale


def demo_user(session: Session) -> User | None:
    return session.scalars(select(User).where(User.email == DEMO_EMAIL)).one_or_none()


# --- Service ---


def test_seed_loads_the_scale_and_reports_it(service: SeedService) -> None:
    report = service.seed(TINY, seed=42, end_date=END_DATE)

    rows = {stats.table: stats.rows for stats in report.tables}
    assert rows["customers"] == 300
    assert rows["products"] == 40
    assert rows["orders"] == 3_000
    assert 2.1 * 3_000 < rows["order_items"] < 2.4 * 3_000
    assert (report.scale, report.seed, report.end_date) == (TINY, 42, END_DATE)
    assert report.elapsed_seconds == 2.5


def test_seed_creates_a_demo_account_that_can_log_in(
    service: SeedService, session: Session
) -> None:
    report = service.seed(TINY, seed=42, end_date=END_DATE)

    user = demo_user(session)
    assert report.demo_account_created is True
    assert user is not None
    assert PasswordHasher().verify(user.password_hash, DEMO_PASSWORD)


def test_seed_never_changes_an_existing_demo_account(
    service: SeedService, session: Session
) -> None:
    existing = create_user(email=DEMO_EMAIL, full_name="Renamed Demo")
    original_hash = existing.password_hash

    report = service.seed(TINY, seed=42, end_date=END_DATE)

    assert report.demo_account_created is False
    user = demo_user(session)
    assert user is not None
    assert (user.full_name, user.password_hash) == ("Renamed Demo", original_hash)


def test_seeding_twice_keeps_one_demo_account_and_one_dataset(
    service: SeedService, session: Session
) -> None:
    service.seed(TINY, seed=42, end_date=END_DATE)
    second = service.seed(TINY, seed=42, end_date=END_DATE)

    assert second.demo_account_created is False
    assert session.scalar(select(func.count()).where(User.email == DEMO_EMAIL)) == 1
    assert session.scalar(select(func.count()).select_from(Order)) == 3_000


def test_each_seed_bumps_the_data_version(service: SeedService, redis_client: Redis) -> None:
    first = service.seed(TINY, seed=42, end_date=END_DATE)
    second = service.seed(TINY, seed=43, end_date=END_DATE)

    assert (first.data_version, second.data_version) == (1, 2)
    assert redis_client.get(DATA_VERSION_KEY) == "2"


def test_a_failed_seed_does_not_bump_the_data_version(
    service: SeedService, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nobody has signed up when the history starts, so the load fails midway.
    monkeypatch.setattr(generator, "EARLY_CUSTOMER_SHARE", 0.0)

    with pytest.raises(ValueError, match="no customer had signed up"):
        service.seed(TINY, seed=42, end_date=END_DATE)

    assert redis_client.get(DATA_VERSION_KEY) is None


# --- Command ---


def test_seed_command_loads_data_and_prints_the_report(
    app: Flask, tiny_small_scale: SeedScale, session: Session
) -> None:
    result = app.test_cli_runner().invoke(
        args=["seed", "--scale", "small", "--seed", "7", "--end-date", "2026-10-01"]
    )

    assert result.exit_code == 0, result.output
    assert "Seeding the small dataset (3,000 orders, seed 7)." in result.stderr
    assert "orders loaded (100%)" in result.stderr
    assert "history 2023-10-01 to 2026-09-30" in result.stdout
    assert f"Demo account {DEMO_EMAIL}: created." in result.stdout
    assert "Data version: 1." in result.stdout
    assert session.scalar(select(func.count()).select_from(Order)) == 3_000


def test_seed_command_ends_the_history_today_by_default(
    app: Flask, tiny_small_scale: SeedScale, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(clock, "utc_today", lambda: date(2026, 3, 1))

    result = app.test_cli_runner().invoke(args=["seed"])

    assert result.exit_code == 0, result.output
    assert "seed 42" in result.stderr
    assert "history 2023-03-01 to 2026-02-28" in result.stdout


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--scale", "huge"], "Invalid value for '--scale'"),
        (["--seed", "-1"], "Invalid value for '--seed'"),
        (["--end-date", "01/10/2026"], "Invalid value for '--end-date'"),
    ],
)
def test_seed_command_rejects_invalid_options(app: Flask, args: list[str], message: str) -> None:
    result = app.test_cli_runner().invoke(args=["seed", *args])

    assert result.exit_code == 2
    assert message in result.stderr


def test_progress_is_printed_in_steps_of_ten_percent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    printer = ProgressPrinter(total=1_000)

    for loaded in (50, 100, 150, 250, 1_000):
        printer(loaded)

    assert capsys.readouterr().err.splitlines() == [
        "        100 orders loaded (10%)",
        "        250 orders loaded (20%)",
        "      1,000 orders loaded (100%)",
    ]


def test_seed_report_lists_every_table_with_rows_and_size() -> None:
    report = SeedReport(
        scale=SCALES["full"],
        seed=42,
        end_date=date(2026, 10, 8),
        tables=[
            TableStats("customers", 50_000, 9_240_576),
            TableStats("products", 1_000, 122_880),
            TableStats("order_items", 4_478_509, 420_241_408),
        ],
        demo_account_created=False,
        data_version=12,
        elapsed_seconds=83.84,
    )

    assert format_seed_report(report).splitlines() == [
        "Seeded the full dataset with seed 42, history 2023-10-08 to 2026-10-07, in 83.8 s.",
        "",
        "  table               rows       size",
        "  customers         50,000     8.8 MB",
        "  products           1,000     120 kB",
        "  order_items    4,478,509   400.8 MB",
        "",
        f"Demo account {DEMO_EMAIL}: already existed, left unchanged.",
        "Data version: 12.",
    ]


@pytest.mark.parametrize(
    ("size_bytes", "expected"),
    [(0, "0 kB"), (24_576, "24 kB"), (9_240_576, "8.8 MB"), (3 * 1024**3, "3.00 GB")],
)
def test_sizes_are_formatted_in_binary_units(size_bytes: int, expected: str) -> None:
    assert format_size(size_bytes) == expected
