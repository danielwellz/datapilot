"""Loads the sales dataset and makes sure the demo account exists."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from redis import Redis
from sqlalchemy.orm import Session

from app.models import User
from app.repositories.users import UserRepository
from app.seed.generator import SeedScale, generate_sales_data
from app.seed.loader import (
    ProgressCallback,
    TableStats,
    load_sales_data,
    psycopg_connection,
    table_stats,
)
from app.services.passwords import PasswordHasher

DEMO_EMAIL = "demo@datapilot.dev"
# Published in the README so anyone running the demo can log in; it guards
# nothing but synthetic data.
DEMO_PASSWORD = "DataPilot-demo-2026"  # noqa: S105
DEMO_FULL_NAME = "Demo Analyst"

# Bumped after every seed. Analytics caches put it in their keys, so a new
# dataset never serves numbers cached from the old one.
DATA_VERSION_KEY = "data_version"


@dataclass(frozen=True, slots=True)
class SeedReport:
    scale: SeedScale
    seed: int
    end_date: date
    tables: list[TableStats]
    demo_account_created: bool
    data_version: int
    elapsed_seconds: float


class SeedService:
    """Replaces the sales data in one transaction and announces the new version."""

    def __init__(
        self,
        session: Session,
        redis: Redis,
        passwords: PasswordHasher,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._redis = redis
        self._passwords = passwords
        self._clock = clock

    def seed(
        self,
        scale: SeedScale,
        *,
        seed: int,
        end_date: date,
        on_progress: ProgressCallback | None = None,
    ) -> SeedReport:
        """Load ``scale`` for ``seed`` with a history ending before ``end_date``.

        The data version is bumped only after the commit: a cache filled in
        between still carries the old version and is simply never read again.
        """
        started = self._clock()
        connection = psycopg_connection(self._session)
        load_sales_data(
            connection, generate_sales_data(scale, seed, end_date), on_progress=on_progress
        )
        demo_account_created = self._ensure_demo_account()
        self._session.commit()
        data_version = int(self._redis.incr(DATA_VERSION_KEY))
        elapsed = self._clock() - started

        return SeedReport(
            scale=scale,
            seed=seed,
            end_date=end_date,
            tables=table_stats(psycopg_connection(self._session)),
            demo_account_created=demo_account_created,
            data_version=data_version,
            elapsed_seconds=elapsed,
        )

    def _ensure_demo_account(self) -> bool:
        """Create the demo account if it is missing; never touch an existing one."""
        if self._users.get_by_email(DEMO_EMAIL) is not None:
            return False
        self._users.add(
            User(
                email=DEMO_EMAIL,
                full_name=DEMO_FULL_NAME,
                password_hash=self._passwords.hash(DEMO_PASSWORD),
            )
        )
        return True
