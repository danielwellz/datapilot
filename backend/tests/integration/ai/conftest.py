"""Fixtures for Ask your data: SQL as the read-only role, scripted models, the service.

Running SQL as the read-only role inside the test's transaction: a real login
as datapilot_readonly would not see rows a test inserted, because they are
never committed. ``SET LOCAL ROLE`` on the test's own connection gives the
role's privileges while seeing those rows. The savepoint around it is always
rolled back, never released: a released savepoint would keep the role
switch in force for the rest of the test.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session, scoped_session

from app.ai.answer import LLMAnswer
from app.ai.clients.base import LLMClient, LLMResult, TokenUsage
from app.ai.clients.fake import FakeLLMClient
from app.ai.executor import QueryResult, apply_query_limits, fetch_result
from app.ai.prompt import Prompt
from app.ai.registry import ModelRegistry, RegisteredModel, RegistryConfig
from app.ai.sql_guard import GuardedSql
from app.services.ask import AskService, QueryRunner
from app.services.rate_limiter import FixedWindowRateLimiter

RunAsReadonly = Callable[[str], list[tuple[Any, ...]]]
TEST_USAGE = TokenUsage(input_tokens=100, output_tokens=20)


@contextmanager
def readonly_connection(
    session: scoped_session[Session], statement_timeout_ms: int = 5000
) -> Iterator[Connection]:
    savepoint = session.begin_nested()
    try:
        connection = session.connection()
        connection.exec_driver_sql("SET LOCAL ROLE datapilot_readonly")
        apply_query_limits(connection, statement_timeout_ms)
        yield connection
    finally:
        savepoint.rollback()


@pytest.fixture
def run_as_readonly(db_session: scoped_session[Session]) -> RunAsReadonly:
    def run(sql: str) -> list[tuple[Any, ...]]:
        with readonly_connection(db_session) as connection:
            # Through psycopg without parameters and with binary results,
            # exactly as the executor runs model-written SQL.
            driver = connection.connection.driver_connection
            assert driver is not None
            return [tuple(row) for row in driver.execute(sql, binary=True).fetchall()]

    return run


class SessionRunner:
    """Runs guarded SQL like the executor, but on the test's connection, so it sees test data."""

    def __init__(self, session: scoped_session[Session], statement_timeout_ms: int) -> None:
        self._session = session
        self._statement_timeout_ms = statement_timeout_ms
        self.queries: list[str] = []

    def run(self, guarded: GuardedSql) -> QueryResult:
        self.queries.append(guarded.sql)
        with readonly_connection(self._session, self._statement_timeout_ms) as connection:
            return fetch_result(connection, guarded)


class ScriptedLLMClient:
    """A model that gives prepared answers (or raises prepared errors) in order."""

    def __init__(self, *steps: LLMAnswer | LLMResult | Exception) -> None:
        self._steps = list(steps)
        self.prompts: list[Prompt] = []

    def answer(self, prompt: Prompt) -> LLMResult:
        self.prompts.append(prompt)
        step = self._steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step if isinstance(step, LLMResult) else LLMResult(step, TEST_USAGE)


def answer(sql: str | None, *, chart: str = "none") -> LLMAnswer:
    return LLMAnswer.model_validate(
        {"sql": sql, "explanation": "What the result shows.", "chart": chart, "assumptions": []}
    )


# Two keyed providers and the demo model; alpha-1 is the default and
# beta-1 the configured fallback.
TEST_REGISTRY = RegistryConfig.model_validate(
    {
        "providers": {
            "alpha": {
                "type": "openai_compatible",
                "label": "Alpha",
                "base_url": "https://alpha.example/v1",
                "api_key_env": "ALPHA_API_KEY",
            },
            "beta": {
                "type": "openai_compatible",
                "label": "Beta",
                "base_url": "https://beta.example/v1",
                "api_key_env": "BETA_API_KEY",
            },
            "fake": {"type": "fake", "label": "Demo"},
        },
        "models": [
            {
                "id": "alpha-1",
                "provider": "alpha",
                "label": "Alpha One",
                "provider_model": "a1",
                "json_schema": True,
            },
            {
                "id": "beta-1",
                "provider": "beta",
                "label": "Beta One",
                "provider_model": "b1",
                "json_schema": True,
            },
            {
                "id": "fake",
                "provider": "fake",
                "label": "Demo",
                "provider_model": "fake",
                "json_schema": False,
            },
        ],
    }
)


@pytest.fixture
def registry() -> ModelRegistry:
    keys = {"ALPHA_API_KEY": SecretStr("a"), "BETA_API_KEY": SecretStr("b")}
    return ModelRegistry(TEST_REGISTRY, api_keys=keys, fallback_models=["beta-1"])


MakeService = Callable[..., tuple[AskService, SessionRunner]]


@pytest.fixture
def make_service(
    db_session: scoped_session[Session], redis_client: Redis, registry: ModelRegistry
) -> MakeService:
    """An AskService over the test transaction; ``clients`` maps model ids to scripted models."""

    def build(
        clients: dict[str, LLMClient] | None = None,
        *,
        max_rows: int = 1000,
        statement_timeout_ms: int = 5000,
        rate_limit: int = 10,
        runner: QueryRunner | None = None,
    ) -> tuple[AskService, SessionRunner]:
        chosen = {"fake": FakeLLMClient(), **(clients or {})}

        def client_for(model: RegisteredModel) -> LLMClient:
            return chosen[model.id]

        session_runner = SessionRunner(db_session, statement_timeout_ms)
        service = AskService(
            db_session(),
            registry=registry,
            client_for=client_for,
            runner=runner or session_runner,
            rate_limiter=FixedWindowRateLimiter(
                redis_client, name="ai-ask", limit=rate_limit, window_seconds=60
            ),
            describe_schema=lambda: "v_orders: One row per order.",
            max_rows=max_rows,
            statement_timeout_ms=statement_timeout_ms,
        )
        return service, session_runner

    return build


@pytest.fixture
def scalar(db_session: scoped_session[Session]) -> Callable[[str], Any]:
    def run(sql: str) -> Any:
        return db_session.execute(text(sql)).scalar_one()

    return run
