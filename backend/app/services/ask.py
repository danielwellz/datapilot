"""Ask your data: a question in, a guarded read-only answer out, every outcome audited.

The steps, in order:

1. The model id is checked against the registry and the per-user rate limit
   is counted. Neither is audited: no question has been processed yet.
2. The prompt goes to the chosen model. If its provider is rate limited,
   failing or unavailable, the next configured fallback model is tried. A
   model that answers unusably (after its own one retry) is not replaced.
3. The SQL in the answer goes through the guard, then runs as the read-only
   role with a statement timeout and a row limit.
4. If PostgreSQL refuses the query with an error a model can fix, the model
   that answered gets one repair attempt with the error, and its new SQL
   goes through the guard and the database again. A guard rejection or a
   timeout is final: retrying either would let a model probe the defenses
   or double the cost of a heavy query.
5. One audit row records the outcome, whatever it was.

Model output is untrusted at every step, whichever model wrote it.
"""

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from pydantic import JsonValue
from sqlalchemy.orm import Session

from app.ai.answer import ChartKind, LLMAnswer
from app.ai.clients.base import InvalidModelOutputError, LLMClient, ProviderError, ProviderFailure
from app.ai.errors import (
    LlmInvalidOutput,
    LlmRateLimited,
    LlmUnavailable,
    QueryFailed,
    QueryTimeout,
    QuestionUnanswerable,
    SqlRejected,
    receipt,
)
from app.ai.executor import QueryFailedError, QueryRefusedError, QueryResult, QueryTimeoutError
from app.ai.prompt import PROMPT_VERSION, Prompt, build_prompt, repair_request
from app.ai.registry import ModelRegistry, RegisteredModel
from app.ai.sql_guard import GuardedSql, SqlRejectedError, guard_sql
from app.errors import AppError, RateLimited
from app.models import AiQuery, AiQueryStatus
from app.services.rate_limiter import FixedWindowRateLimiter

logger = logging.getLogger(__name__)

# The code the error handler gives unexpected failures, recorded for them too.
INTERNAL_ERROR_CODE = "internal_error"


class QueryRunner(Protocol):
    def run(self, guarded: GuardedSql) -> QueryResult: ...


ClientFactory = Callable[[RegisteredModel], LLMClient]


@dataclass(frozen=True, slots=True)
class AskAnswer:
    audit_id: int
    question: str
    requested_model: str
    # The model that answered, after any fallback.
    model: RegisteredModel
    # The SQL that ran: the guard's rewrite of the model's last query.
    sql: str
    explanation: str
    chart: ChartKind
    assumptions: list[str]
    result: QueryResult
    repaired: bool
    latency_ms: int
    prompt_version: str
    created_at: datetime


@dataclass
class _UnansweredError(Exception):
    """Ends a question without an answer; ``ask`` audits it, then raises ``error``."""

    error: type[AppError]
    status: AiQueryStatus
    message: str | None = None
    sql: str | None = None
    retry_after_seconds: int | None = None
    extra: dict[str, JsonValue] = field(default_factory=dict)


class AskService:
    def __init__(
        self,
        session: Session,
        *,
        registry: ModelRegistry,
        client_for: ClientFactory,
        runner: QueryRunner,
        rate_limiter: FixedWindowRateLimiter,
        describe_schema: Callable[[], str],
        max_rows: int,
        statement_timeout_ms: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._registry = registry
        self._client_for = client_for
        self._runner = runner
        self._rate_limiter = rate_limiter
        self._describe_schema = describe_schema
        self._max_rows = max_rows
        self._statement_timeout_ms = statement_timeout_ms
        self._clock = clock

    def ask(self, user_id: int, question: str, model_id: str | None) -> AskAnswer:
        """Answer ``question`` with the model ``model_id`` (the default when None)."""
        requested = self._registry.resolve(model_id)
        self._enforce_rate_limit(user_id)

        started = self._clock()
        audit = AiQuery(
            user_id=user_id,
            question=question,
            requested_model=requested.id,
            prompt_version=PROMPT_VERSION,
            latency_ms=0,
            assumptions=[],
        )
        try:
            model, answer, guarded, result = self._answer(audit, requested, question)
        except _UnansweredError as failure:
            self._finish(audit, started, failure.status, failure.error.code)
            raise self._error(failure, audit) from failure.__cause__
        except Exception:
            # Something broke (the read-only database, a bug): the question
            # is still audited, with what was known, before the error goes on.
            self._audit_unexpected_failure(audit, started)
            raise

        audit.row_count = result.row_count
        audit.truncated = result.truncated
        self._finish(audit, started, AiQueryStatus.OK, None)
        return AskAnswer(
            audit_id=audit.id,
            question=question,
            requested_model=requested.id,
            model=model,
            sql=guarded.sql,
            explanation=answer.explanation,
            chart=answer.chart,
            assumptions=list(answer.assumptions),
            result=result,
            repaired=audit.repaired,
            latency_ms=audit.latency_ms,
            prompt_version=PROMPT_VERSION,
            created_at=audit.created_at,
        )

    def _enforce_rate_limit(self, user_id: int) -> None:
        decision = self._rate_limiter.hit(f"user:{user_id}")
        if not decision.allowed:
            raise RateLimited(
                decision.retry_after_seconds,
                f"You can ask {self._rate_limiter.limit} questions a minute. "
                f"Try again in {decision.retry_after_seconds} seconds.",
            )

    def _answer(
        self, audit: AiQuery, requested: RegisteredModel, question: str
    ) -> tuple[RegisteredModel, LLMAnswer, GuardedSql, QueryResult]:
        prompt = build_prompt(question, self._describe_schema())
        model, answer = self._complete(audit, self._registry.attempt_order(requested), prompt)
        guarded = self._guard(audit, answer)
        try:
            return model, answer, guarded, self._execute(guarded)
        except QueryFailedError as error:
            database_error = error

        # One repair, by the model that wrote the query, with PostgreSQL's error.
        audit.repaired = True
        logger.info(
            "query failed; asking the model for a repair",
            extra={"model": model.id, "sqlstate": database_error.sqlstate},
        )
        repair_prompt = prompt.followed_by(*repair_request(answer, database_error.message))
        try:
            repaired = self._client_for(model).answer(repair_prompt)
        except (ProviderError, InvalidModelOutputError) as error:
            if isinstance(error, InvalidModelOutputError):
                _add_usage(audit, error.usage.input_tokens, error.usage.output_tokens)
            raise self._query_failed(database_error, guarded) from error
        _add_usage(audit, repaired.usage.input_tokens, repaired.usage.output_tokens)
        if repaired.answer.sql is None:
            raise self._query_failed(database_error, guarded)
        guarded = self._guard(audit, repaired.answer)
        try:
            return model, repaired.answer, guarded, self._execute(guarded)
        except QueryFailedError as error:
            raise self._query_failed(error, guarded) from error

    def _complete(
        self, audit: AiQuery, models: list[RegisteredModel], prompt: Prompt
    ) -> tuple[RegisteredModel, LLMAnswer]:
        """The first answer from ``models`` in order, moving on only when a provider fails."""
        failures: list[tuple[RegisteredModel, ProviderError]] = []
        for model in models:
            try:
                result = self._client_for(model).answer(prompt)
            except ProviderError as error:
                logger.warning(
                    "model provider failed",
                    extra={
                        "model": model.id,
                        "provider": model.provider_id,
                        "failure": error.failure.value,
                    },
                )
                failures.append((model, error))
                continue
            except InvalidModelOutputError as error:
                audit.model, audit.provider = model.id, model.provider_id
                _add_usage(audit, error.usage.input_tokens, error.usage.output_tokens)
                raise _UnansweredError(LlmInvalidOutput, AiQueryStatus.ERROR) from error
            audit.model, audit.provider = model.id, model.provider_id
            _add_usage(audit, result.usage.input_tokens, result.usage.output_tokens)
            return model, result.answer
        raise self._no_model_answered(failures)

    def _guard(self, audit: AiQuery, answer: LLMAnswer) -> GuardedSql:
        audit.generated_sql = answer.sql
        audit.explanation = answer.explanation
        audit.chart = answer.chart
        audit.assumptions = list(answer.assumptions)
        if answer.sql is None:
            raise _UnansweredError(
                QuestionUnanswerable, AiQueryStatus.ERROR, message=answer.explanation
            )
        try:
            guarded = guard_sql(answer.sql, max_rows=self._max_rows)
        except SqlRejectedError as error:
            logger.warning(
                "generated sql rejected by the guard",
                extra={"model": audit.model, "reason": error.reason.value},
            )
            raise _UnansweredError(
                SqlRejected,
                AiQueryStatus.REJECTED,
                message=f"{SqlRejected.default_message} {error.message}",
                sql=answer.sql,
                extra={"reason": error.reason.value},
            ) from error
        audit.executed_sql = guarded.sql
        return guarded

    def _execute(self, guarded: GuardedSql) -> QueryResult:
        """Run ``guarded``; a ``QueryFailedError`` is left for the caller to repair."""
        try:
            return self._runner.run(guarded)
        except QueryTimeoutError as error:
            seconds = self._statement_timeout_ms / 1000
            raise _UnansweredError(
                QueryTimeout,
                AiQueryStatus.ERROR,
                message=(
                    f"The query took longer than {seconds:g} seconds and was stopped. "
                    "Try a narrower question, for example over a shorter period."
                ),
                sql=guarded.sql,
            ) from error
        except QueryRefusedError as error:
            # The guard should have caught this: the role is the last layer,
            # and it just had to act. Worth an error in the logs.
            logger.error(
                "read-only role refused sql that passed the guard",
                extra={"sqlstate": error.sqlstate},
            )
            raise _UnansweredError(
                SqlRejected, AiQueryStatus.REJECTED, sql=guarded.sql, extra={"reason": "database"}
            ) from error

    @staticmethod
    def _query_failed(error: QueryFailedError, guarded: GuardedSql) -> _UnansweredError:
        return _UnansweredError(
            QueryFailed,
            AiQueryStatus.ERROR,
            message=(
                "The database could not run the generated query, even after one correction. "
                f"Its error was: {error.message}"
            ),
            sql=guarded.sql,
        )

    @staticmethod
    def _no_model_answered(
        failures: list[tuple[RegisteredModel, ProviderError]],
    ) -> _UnansweredError:
        tried = [model.id for model, _ in failures]
        labels = ", ".join(model.label for model, _ in failures)
        extra: dict[str, JsonValue] = {"attempted_models": list(tried)}
        if all(error.failure is ProviderFailure.RATE_LIMITED for _, error in failures):
            waits = [error.retry_after for _, error in failures if error.retry_after is not None]
            retry_after = math.ceil(min(waits)) if waits else None
            when = f"in {retry_after} seconds" if retry_after is not None else "later"
            return _UnansweredError(
                LlmRateLimited,
                AiQueryStatus.ERROR,
                message=(
                    f"The provider of {labels} is rate limiting requests or has reached its "
                    f"daily limit. Try again {when}, or pick another model."
                ),
                retry_after_seconds=retry_after,
                extra=extra,
            )
        return _UnansweredError(
            LlmUnavailable,
            AiQueryStatus.ERROR,
            message=f"No model could answer right now (tried {labels}). "
            "Try again shortly, or pick another model.",
            extra=extra,
        )

    def _finish(
        self, audit: AiQuery, started: float, status: AiQueryStatus, error_code: str | None
    ) -> None:
        audit.status = status
        audit.error_code = error_code
        audit.latency_ms = round((self._clock() - started) * 1000)
        self._session.add(audit)
        self._session.commit()
        logger.info(
            "question answered" if status is AiQueryStatus.OK else "question not answered",
            extra={
                "audit_id": audit.id,
                "status": status.value,
                "error_code": error_code,
                "model": audit.model,
                "provider": audit.provider,
                "latency_ms": audit.latency_ms,
            },
        )

    def _audit_unexpected_failure(self, audit: AiQuery, started: float) -> None:
        try:
            self._session.rollback()
            self._finish(audit, started, AiQueryStatus.ERROR, INTERNAL_ERROR_CODE)
        except Exception:
            # The original error matters more than the audit row; keep it.
            logger.exception("could not audit a question that failed unexpectedly")

    @staticmethod
    def _error(failure: _UnansweredError, audit: AiQuery) -> AppError:
        details = receipt(
            audit_id=audit.id,
            requested_model=audit.requested_model,
            model=audit.model,
            provider=audit.provider,
            sql=failure.sql,
            **failure.extra,
        )
        if failure.error is LlmRateLimited:
            return LlmRateLimited(failure.retry_after_seconds, failure.message, details=details)
        return failure.error(failure.message, details=details)


def _add_usage(audit: AiQuery, input_tokens: int | None, output_tokens: int | None) -> None:
    if input_tokens is not None:
        audit.input_tokens = (audit.input_tokens or 0) + input_tokens
    if output_tokens is not None:
        audit.output_tokens = (audit.output_tokens or 0) + output_tokens
