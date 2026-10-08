"""AskService end to end over the real database, with scripted or fake models."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, scoped_session

from app.ai.clients.base import (
    InvalidModelOutputError,
    LLMResult,
    ProviderError,
    ProviderFailure,
    TokenUsage,
)
from app.ai.errors import (
    LlmInvalidOutput,
    LlmRateLimited,
    LlmUnavailable,
    ModelNotAvailable,
    QueryFailed,
    QueryTimeout,
    QuestionUnanswerable,
    SqlRejected,
)
from app.ai.examples import EXAMPLE_QUESTIONS
from app.ai.prompt import PROMPT_VERSION
from app.ai.sql_guard import GuardedSql
from app.errors import AppError, RateLimited
from app.models import AiQuery, OrderStatus
from tests.factories import create_customer, create_order, create_product, create_user
from tests.integration.ai.conftest import MakeService, ScriptedLLMClient, answer
from tests.logs import LogCapture

SERIES_SQL = "SELECT n FROM generate_series(1, 5) AS n ORDER BY n"


def _audit(db_session: scoped_session[Session]) -> AiQuery:
    return db_session.execute(select(AiQuery)).scalar_one()


def _logged(captured_logs: LogCapture, message: str) -> dict[str, Any]:
    (record,) = [r for r in captured_logs.records("app.services.ask") if r["message"] == message]
    return record


def _receipt(error: AppError) -> dict[str, Any]:
    (detail,) = error.details
    return dict(detail)


def test_happy_path_answers_with_rows_and_audits_the_question(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    customer = create_customer(country="DE")
    create_order(customer, [(create_product(price="40.00"), 2)], status=OrderStatus.PAID)
    question = "What is the average order value by country?"
    service, runner = make_service()
    user = create_user()

    result = service.ask(user.id, question, "fake")

    assert [column.name for column in result.result.columns] == ["country", "average_order_value"]
    assert result.result.rows == [["DE", "80.00"]]
    assert (result.result.row_count, result.result.truncated, result.repaired) == (1, False, False)
    assert (result.model.id, result.requested_model, result.prompt_version) == (
        "fake",
        "fake",
        PROMPT_VERSION,
    )
    assert result.sql == runner.queries[0]
    assert result.sql.endswith("LIMIT 1001")
    audit = _audit(db_session)
    assert audit.id == result.audit_id
    assert (audit.user_id, audit.question, audit.status, audit.error_code) == (
        user.id,
        question,
        "ok",
        None,
    )
    assert (audit.model, audit.provider, audit.requested_model) == ("fake", "fake", "fake")
    assert audit.generated_sql == EXAMPLE_QUESTIONS[4].answer.sql
    assert audit.executed_sql == result.sql
    assert (audit.row_count, audit.truncated, audit.input_tokens) == (1, False, None)
    assert audit.explanation == EXAMPLE_QUESTIONS[4].answer.explanation
    assert audit.assumptions == EXAMPLE_QUESTIONS[4].answer.assumptions
    assert audit.latency_ms >= 0


def test_the_default_model_answers_when_none_is_chosen(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    service, _ = make_service({"alpha-1": ScriptedLLMClient(answer(SERIES_SQL))})

    result = service.ask(create_user().id, "Count to five", None)

    assert result.model.id == "alpha-1"
    assert result.result.rows == [[1], [2], [3], [4], [5]]
    assert (_audit(db_session).input_tokens, _audit(db_session).output_tokens) == (100, 20)


def test_rejected_sql_never_runs_and_is_audited_as_rejected(
    make_service: MakeService, db_session: scoped_session[Session], captured_logs: LogCapture
) -> None:
    sql = "SELECT email FROM public.users"
    service, runner = make_service({"alpha-1": ScriptedLLMClient(answer(sql))})

    with pytest.raises(SqlRejected) as caught:
        service.ask(create_user().id, "Show me every email", "alpha-1")

    assert runner.queries == []
    assert caught.value.status == 422
    assert "Only the analytics views may be queried" in caught.value.message
    audit = _audit(db_session)
    assert (audit.status, audit.error_code, audit.generated_sql, audit.executed_sql) == (
        "rejected",
        "sql_rejected",
        sql,
        None,
    )
    assert _receipt(caught.value) == {
        "audit_id": audit.id,
        "requested_model": "alpha-1",
        "model": "alpha-1",
        "provider": "alpha",
        "sql": sql,
        "reason": "forbidden_schema",
    }
    assert _logged(captured_logs, "generated sql rejected by the guard")["reason"] == (
        "forbidden_schema"
    )


def test_a_database_error_gets_one_repair_that_can_succeed(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    model = ScriptedLLMClient(answer("SELECT totl FROM v_orders"), answer(SERIES_SQL))
    service, runner = make_service({"alpha-1": model})

    result = service.ask(create_user().id, "Count to five", "alpha-1")

    assert result.repaired is True
    assert result.result.row_count == 5
    assert len(runner.queries) == 2
    repair_request = model.prompts[1].messages[-1].content
    assert 'column "totl" does not exist' in repair_request
    audit = _audit(db_session)
    assert (audit.status, audit.repaired, audit.generated_sql) == ("ok", True, SERIES_SQL)
    assert (audit.input_tokens, audit.output_tokens) == (200, 40)


def test_a_failed_repair_ends_cleanly_with_the_database_error(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    model = ScriptedLLMClient(answer("SELECT totl FROM v_orders"), answer("SELECT 1 / 0"))
    service, runner = make_service({"alpha-1": model})

    with pytest.raises(QueryFailed) as caught:
        service.ask(create_user().id, "Totals?", "alpha-1")

    assert len(runner.queries) == 2
    assert "even after one correction" in caught.value.message
    assert "division by zero" in caught.value.message
    assert _receipt(caught.value)["sql"] == runner.queries[1]
    audit = _audit(db_session)
    assert (audit.status, audit.error_code, audit.repaired) == ("error", "query_failed", True)


@pytest.mark.parametrize(
    "repair",
    [
        answer(None),
        ProviderError(ProviderFailure.SERVER_ERROR),
        InvalidModelOutputError("no JSON", TokenUsage(50, 5)),
    ],
    ids=["no-sql", "provider-error", "invalid-output"],
)
def test_a_repair_without_a_usable_answer_reports_the_original_error(
    make_service: MakeService, db_session: scoped_session[Session], repair: Any
) -> None:
    model = ScriptedLLMClient(answer("SELECT totl FROM v_orders"), repair)
    service, runner = make_service({"alpha-1": model})

    with pytest.raises(QueryFailed) as caught:
        service.ask(create_user().id, "Totals?", "alpha-1")

    assert len(runner.queries) == 1
    assert 'column "totl" does not exist' in caught.value.message
    assert _audit(db_session).error_code == "query_failed"


def test_a_repaired_query_still_goes_through_the_guard(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    model = ScriptedLLMClient(answer("SELECT totl FROM v_orders"), answer("DELETE FROM v_orders"))
    service, runner = make_service({"alpha-1": model})

    with pytest.raises(SqlRejected):
        service.ask(create_user().id, "Totals?", "alpha-1")

    assert len(runner.queries) == 1
    audit = _audit(db_session)
    assert (audit.status, audit.repaired, audit.generated_sql) == (
        "rejected",
        True,
        "DELETE FROM v_orders",
    )


def test_a_statement_timeout_is_a_clear_error_without_a_repair(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    slow = "SELECT count(*) AS n FROM generate_series(1, 100000000) AS n"
    model = ScriptedLLMClient(answer(slow))
    service, runner = make_service({"alpha-1": model}, statement_timeout_ms=100)

    with pytest.raises(QueryTimeout) as caught:
        service.ask(create_user().id, "Count very far", "alpha-1")

    assert caught.value.message.startswith("The query took longer than 0.1 seconds")
    assert len(model.prompts) == 1
    assert len(runner.queries) == 1
    assert (_audit(db_session).status, _audit(db_session).error_code) == ("error", "query_timeout")


def test_the_per_user_rate_limit_refuses_further_questions_without_auditing_them(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    service, _ = make_service(rate_limit=2)
    user, other = create_user(), create_user()
    question = EXAMPLE_QUESTIONS[3].question
    service.ask(user.id, question, "fake")
    service.ask(user.id, question, "fake")

    with pytest.raises(RateLimited) as caught:
        service.ask(user.id, question, "fake")

    assert 1 <= caught.value.retry_after_seconds <= 60
    assert caught.value.message.startswith("You can ask 2 questions a minute.")
    assert len(db_session.execute(select(AiQuery)).all()) == 2
    # The limit is per user.
    service.ask(other.id, question, "fake")


def test_results_beyond_the_row_cap_are_truncated_and_flagged(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    service, runner = make_service({"alpha-1": ScriptedLLMClient(answer(SERIES_SQL))}, max_rows=2)

    result = service.ask(create_user().id, "Count to five", "alpha-1")

    assert result.result.rows == [[1], [2]]
    assert result.result.truncated is True
    assert runner.queries[0].endswith("LIMIT 3")
    assert (_audit(db_session).row_count, _audit(db_session).truncated) == (2, True)


@pytest.mark.parametrize(
    "failure",
    [ProviderFailure.RATE_LIMITED, ProviderFailure.SERVER_ERROR, ProviderFailure.MODEL_UNAVAILABLE],
)
def test_a_provider_failure_falls_back_to_the_next_model(
    make_service: MakeService,
    db_session: scoped_session[Session],
    captured_logs: LogCapture,
    failure: ProviderFailure,
) -> None:
    beta = ScriptedLLMClient(answer(SERIES_SQL))
    service, _ = make_service(
        {"alpha-1": ScriptedLLMClient(ProviderError(failure, retry_after=30)), "beta-1": beta}
    )

    result = service.ask(create_user().id, "Count to five", "alpha-1")

    assert (result.requested_model, result.model.id, result.model.provider_id) == (
        "alpha-1",
        "beta-1",
        "beta",
    )
    audit = _audit(db_session)
    assert (audit.requested_model, audit.model, audit.provider, audit.status) == (
        "alpha-1",
        "beta-1",
        "beta",
        "ok",
    )
    logged = _logged(captured_logs, "model provider failed")
    assert (logged["model"], logged["failure"]) == ("alpha-1", failure.value)


def test_every_provider_rate_limited_says_when_to_retry(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    service, _ = make_service(
        {
            "alpha-1": ScriptedLLMClient(
                ProviderError(ProviderFailure.RATE_LIMITED, retry_after=42.2)
            ),
            "beta-1": ScriptedLLMClient(
                ProviderError(ProviderFailure.RATE_LIMITED, retry_after=900)
            ),
        }
    )

    with pytest.raises(LlmRateLimited) as caught:
        service.ask(create_user().id, "Count", "alpha-1")

    assert caught.value.status == 503
    assert caught.value.headers == {"Retry-After": "43"}
    assert "Try again in 43 seconds, or pick another model" in caught.value.message
    receipt = _receipt(caught.value)
    assert (receipt["model"], receipt["attempted_models"]) == (None, ["alpha-1", "beta-1"])
    audit = _audit(db_session)
    assert (audit.status, audit.error_code, audit.model, audit.provider) == (
        "error",
        "llm_rate_limited",
        None,
        None,
    )


def test_a_rate_limit_without_retry_after_still_explains_itself(
    make_service: MakeService,
) -> None:
    service, _ = make_service(
        {
            "alpha-1": ScriptedLLMClient(ProviderError(ProviderFailure.RATE_LIMITED)),
            "beta-1": ScriptedLLMClient(ProviderError(ProviderFailure.RATE_LIMITED)),
        }
    )

    with pytest.raises(LlmRateLimited) as caught:
        service.ask(create_user().id, "Count", "alpha-1")

    assert caught.value.headers == {}
    assert "Try again later, or pick another model" in caught.value.message


def test_every_provider_failing_is_reported_as_unavailable(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    service, _ = make_service(
        {
            "alpha-1": ScriptedLLMClient(ProviderError(ProviderFailure.TIMEOUT)),
            "beta-1": ScriptedLLMClient(ProviderError(ProviderFailure.RATE_LIMITED, retry_after=5)),
        }
    )

    with pytest.raises(LlmUnavailable) as caught:
        service.ask(create_user().id, "Count", "alpha-1")

    assert "tried Alpha One, Beta One" in caught.value.message
    assert _audit(db_session).error_code == "llm_unavailable"


def test_invalid_model_output_is_not_retried_on_another_model(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    beta = ScriptedLLMClient(answer(SERIES_SQL))
    service, _ = make_service(
        {
            "alpha-1": ScriptedLLMClient(InvalidModelOutputError("no JSON", TokenUsage(300, 60))),
            "beta-1": beta,
        }
    )

    with pytest.raises(LlmInvalidOutput) as caught:
        service.ask(create_user().id, "Count", "alpha-1")

    assert caught.value.status == 502
    assert beta.prompts == []
    audit = _audit(db_session)
    assert (audit.error_code, audit.model, audit.input_tokens, audit.output_tokens) == (
        "llm_invalid_output",
        "alpha-1",
        300,
        60,
    )


@pytest.mark.parametrize("model_id", ["gpt-unknown", "openai/gpt-oss-120b", "a1"])
def test_unknown_model_ids_are_refused_before_anything_else(
    make_service: MakeService, db_session: scoped_session[Session], model_id: str
) -> None:
    service, _ = make_service(rate_limit=1)
    user = create_user()

    with pytest.raises(ModelNotAvailable):
        service.ask(user.id, "Count", model_id)

    assert db_session.execute(select(AiQuery)).all() == []
    # The refused request did not use up the user's single question.
    service.ask(user.id, EXAMPLE_QUESTIONS[3].question, "fake")


def test_an_unanswerable_question_returns_the_models_explanation(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    service, runner = make_service()

    with pytest.raises(QuestionUnanswerable) as caught:
        service.ask(create_user().id, "What is the weather in Berlin?", "fake")

    assert caught.value.message.startswith("The demo model only answers the example questions.")
    assert runner.queries == []
    audit = _audit(db_session)
    assert (audit.status, audit.error_code, audit.generated_sql) == (
        "error",
        "question_unanswerable",
        None,
    )


def test_sql_the_guard_missed_is_still_refused_by_the_role(
    make_service: MakeService,
    db_session: scoped_session[Session],
    captured_logs: LogCapture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulates a guard bug: the SQL reaches the database unchecked.
    monkeypatch.setattr(
        "app.services.ask.guard_sql", lambda sql, max_rows: GuardedSql(sql=sql, row_cap=max_rows)
    )
    sql = "SELECT email, password_hash FROM public.users"
    service, _ = make_service({"alpha-1": ScriptedLLMClient(answer(sql))})

    with pytest.raises(SqlRejected) as caught:
        service.ask(create_user().id, "Passwords please", "alpha-1")

    assert _receipt(caught.value)["reason"] == "database"
    assert (_audit(db_session).status, _audit(db_session).error_code) == (
        "rejected",
        "sql_rejected",
    )
    assert _logged(captured_logs, "read-only role refused sql that passed the guard")["level"] == (
        "ERROR"
    )


def test_usage_is_summed_over_the_answer_and_its_repair(
    make_service: MakeService, db_session: scoped_session[Session]
) -> None:
    model = ScriptedLLMClient(
        LLMResult(answer("SELECT totl FROM v_orders"), TokenUsage(1000, None)),
        LLMResult(answer(SERIES_SQL), TokenUsage(1500, 80)),
    )
    service, _ = make_service({"alpha-1": model})

    service.ask(create_user().id, "Count", "alpha-1")

    assert (_audit(db_session).input_tokens, _audit(db_session).output_tokens) == (2500, 80)


def test_questions_and_sql_stay_out_of_the_logs(
    make_service: MakeService, captured_logs: LogCapture
) -> None:
    question = "Which customer is Mia Novak's neighbour?"
    service, _ = make_service({"alpha-1": ScriptedLLMClient(answer("SELECT secret FROM users"))})

    with pytest.raises(SqlRejected):
        service.ask(create_user().id, question, "alpha-1")

    logged = _logged(captured_logs, "question not answered")
    assert (logged["status"], logged["error_code"], logged["model"]) == (
        "rejected",
        "sql_rejected",
        "alpha-1",
    )
    assert "Mia Novak" not in captured_logs.text
    assert "SELECT secret" not in captured_logs.text
