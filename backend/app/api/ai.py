"""Ask your data endpoints: models, example questions, asking, and history."""

from flask import Blueprint, current_app
from spectree import Response, Tag

from app.ai.clients.base import LLMClient
from app.ai.clients.factory import create_llm_client
from app.ai.examples import EXAMPLE_QUESTIONS
from app.ai.executor import ReadonlyExecutor
from app.ai.registry import RegisteredModel
from app.ai.schema_description import describe_analytics_views
from app.api.security import BEARER_AUTH, current_user, require_access_token
from app.api.spec import spec
from app.config import current_settings
from app.extensions import db, get_model_registry, get_readonly_engine, get_redis
from app.schemas.ai import (
    AnsweredByOut,
    AskIn,
    AskOut,
    ExampleOut,
    ExamplesOut,
    HistoryItemOut,
    HistoryPageOut,
    HistoryQuery,
    ModelOut,
    ModelsOut,
    ResultColumnOut,
)
from app.schemas.errors import ErrorOut
from app.services.ask import AskService
from app.services.ask_history import AskHistoryService
from app.services.rate_limiter import FixedWindowRateLimiter

ai = Blueprint("ai", __name__, url_prefix="/ai")

_TAGS = [
    Tag(
        name="ai",
        description=(
            "Ask your data: plain-English questions answered with read-only SQL written by a "
            "language model. The SQL is checked, then run as a read-only database role over "
            "curated views, with a timeout and a row limit. Text that comes from the model "
            "(SQL, explanation, assumptions) must be displayed as plain text."
        ),
    )
]

_CLIENTS_EXTENSION_KEY = "datapilot.llm_clients"
_SCHEMA_DESCRIPTION_EXTENSION_KEY = "datapilot.ai_schema_description"
_RATE_LIMIT_WINDOW_SECONDS = 60


def _client_for(model: RegisteredModel) -> LLMClient:
    # One client per model and process: SDK clients hold connection pools,
    # which would be lost if each question built a new one.
    clients: dict[str, LLMClient] = current_app.extensions.setdefault(_CLIENTS_EXTENSION_KEY, {})
    if model.id not in clients:
        settings = current_settings()
        clients[model.id] = create_llm_client(
            model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    return clients[model.id]


def _describe_schema() -> str:
    # Read from the catalog once per process: the views change only with a
    # migration, which comes with a restart.
    description: str | None = current_app.extensions.get(_SCHEMA_DESCRIPTION_EXTENSION_KEY)
    if description is None:
        description = describe_analytics_views(db.session())
        current_app.extensions[_SCHEMA_DESCRIPTION_EXTENSION_KEY] = description
    return description


def _ask_service() -> AskService:
    settings = current_settings()
    return AskService(
        db.session(),
        registry=get_model_registry(),
        client_for=_client_for,
        runner=ReadonlyExecutor(
            get_readonly_engine(), statement_timeout_ms=settings.ai_statement_timeout_ms
        ),
        rate_limiter=FixedWindowRateLimiter(
            get_redis(),
            name="ai-ask",
            limit=settings.ai_rate_limit_per_minute,
            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
        ),
        describe_schema=_describe_schema,
        max_rows=settings.ai_max_rows,
        statement_timeout_ms=settings.ai_statement_timeout_ms,
    )


@ai.get("/models")
@spec.validate(
    resp=Response(HTTP_200=ModelsOut, HTTP_401=ErrorOut), tags=_TAGS, security=BEARER_AUTH
)
@require_access_token
def list_models() -> ModelsOut:
    """The models that can answer questions now, and the default one.

    A model is listed only when its provider is configured (its API key is
    set); the demo model needs no key and answers the example questions.
    """
    registry = get_model_registry()
    return ModelsOut(
        items=[
            ModelOut(
                id=model.id,
                label=model.label,
                provider=model.provider_id,
                provider_label=model.provider.label,
                default=model.id == registry.default_model.id,
            )
            for model in registry.enabled_models
        ],
        default_model=registry.default_model.id,
    )


@ai.get("/examples")
@spec.validate(
    resp=Response(HTTP_200=ExamplesOut, HTTP_401=ErrorOut), tags=_TAGS, security=BEARER_AUTH
)
@require_access_token
def list_examples() -> ExamplesOut:
    """Suggested questions; the demo model answers each of them without an API key."""
    return ExamplesOut(
        items=[ExampleOut(question=example.question) for example in EXAMPLE_QUESTIONS]
    )


@ai.post("/ask")
@spec.validate(
    json=AskIn,
    resp=Response(
        HTTP_200=AskOut,
        HTTP_401=ErrorOut,
        HTTP_422=ErrorOut,
        HTTP_429=ErrorOut,
        HTTP_502=ErrorOut,
        HTTP_503=ErrorOut,
    ),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def ask(json: AskIn) -> AskOut:
    """Answer a question with SQL over the sales data.

    Failures use the standard error envelope. Once a question was processed,
    the error's single detail holds `audit_id`, `requested_model`, `model`,
    `provider` and `sql` (when there was some), so a client can still show
    what happened:

    - 422 `model_not_available`: the model id is not one of `GET /api/ai/models`.
    - 422 `sql_rejected`: the generated SQL was not safe, so it did not run.
    - 422 `question_unanswerable`: the data cannot answer the question.
    - 422 `query_timeout`: the query ran past the time limit.
    - 422 `query_failed`: the database refused the query, even after one correction.
    - 429 `rate_limited`: too many questions this minute; see `Retry-After`.
    - 502 `llm_invalid_output`: the model gave no usable answer.
    - 503 `llm_rate_limited`: every provider tried is rate limited; `Retry-After` when known.
    - 503 `llm_unavailable`: no model could answer.
    """
    result = _ask_service().ask(current_user().id, json.question, json.model)
    return AskOut(
        id=result.audit_id,
        question=result.question,
        requested_model=result.requested_model,
        model=AnsweredByOut(
            id=result.model.id,
            label=result.model.label,
            provider=result.model.provider_id,
            provider_label=result.model.provider.label,
        ),
        fell_back=result.model.id != result.requested_model,
        sql=result.sql,
        explanation=result.explanation,
        chart=result.chart,
        assumptions=result.assumptions,
        columns=[
            ResultColumnOut(name=column.name, type=column.type) for column in result.result.columns
        ],
        rows=result.result.rows,
        row_count=result.result.row_count,
        truncated=result.result.truncated,
        repaired=result.repaired,
        latency_ms=result.latency_ms,
        prompt_version=result.prompt_version,
        created_at=result.created_at,
    )


@ai.get("/history")
@spec.validate(
    query=HistoryQuery,
    resp=Response(HTTP_200=HistoryPageOut, HTTP_400=ErrorOut, HTTP_401=ErrorOut, HTTP_422=ErrorOut),
    tags=_TAGS,
    security=BEARER_AUTH,
)
@require_access_token
def history(query: HistoryQuery) -> HistoryPageOut:
    """The current user's questions, newest first, whatever their outcome.

    Follow `next_cursor` for older questions. Result rows are not kept, so
    an old answer is shown from its SQL and explanation, or asked again.
    """
    secret = current_settings().secret_key.get_secret_value().encode()
    page = AskHistoryService(db.session(), cursor_secret=secret).history(
        current_user().id, limit=query.limit, cursor=query.cursor
    )
    return HistoryPageOut(
        items=[HistoryItemOut.model_validate(row) for row in page.queries],
        next_cursor=page.next_cursor,
    )
