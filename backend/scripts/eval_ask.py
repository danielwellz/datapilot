"""Evaluate Ask your data: the golden questions against every enabled model.

Each model answers the 15 golden questions (the eight example questions and
the seven in ``golden_questions.toml``) through the same AskService as the
API: prompt, guard, read-only execution, one repair. A question passes when
the model's result matches the result of its reference SQL. The script then
writes a comparison table (pass rate, median latency, failures by type) to
``docs/ai-evaluation.md``.

It calls real providers, so it is never part of the test suite or CI. Free
tiers have rate limits: ``--delay`` spaces the questions out. Fallback is
off, so each model is measured on its own. The audit rows it writes are
rolled back. The demo model is left out: it only knows the examples.

Usage, from ``backend/`` with at least one provider key in ``.env``::

    uv run python -m scripts.eval_ask
    uv run python -m scripts.eval_ask --models groq-gpt-oss-120b --delay 5
"""

import argparse
import itertools
import re
import statistics
import sys
import time
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from flask import Flask
from pydantic import JsonValue
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import create_app
from app.ai.clients.base import LLMClient
from app.ai.clients.factory import create_llm_client
from app.ai.examples import EXAMPLE_QUESTIONS
from app.ai.executor import ReadonlyExecutor
from app.ai.prompt import PROMPT_VERSION
from app.ai.registry import (
    DEFAULT_REGISTRY_FILE,
    ModelRegistry,
    RegisteredModel,
    RegistryConfig,
)
from app.ai.schema_description import describe_analytics_views
from app.ai.sql_guard import guard_sql
from app.config import current_settings
from app.errors import AppError
from app.extensions import db, get_model_registry, get_readonly_engine, get_redis
from app.models import Order, User
from app.services.ask import AskService
from app.services.rate_limiter import FixedWindowRateLimiter

GOLDEN_FILE = Path(__file__).with_name("golden_questions.toml")
REPORT_FILE = Path(__file__).resolve().parents[2] / "docs" / "ai-evaluation.md"

CORRECT = "pass"
WRONG_RESULT = "wrong_result"
# Outcomes where no model answered, as opposed to answering wrongly.
PROVIDER_FAILURES = frozenset({"llm_rate_limited", "llm_unavailable"})
_CENT = Decimal("0.01")
_MIDNIGHT = re.compile(r"(\d{4}-\d{2}-\d{2})T00:00:00(?:\.0+)?(?:Z|\+00:00)?")
_YEAR_MONTH = re.compile(r"\d{4}-\d{2}")


@dataclass(frozen=True, slots=True)
class GoldenQuestion:
    id: str
    question: str
    sql: str


@dataclass(frozen=True, slots=True)
class Outcome:
    model: str
    question: str
    # "pass", "wrong_result", or the API error code the question ended with.
    result: str
    latency_ms: int
    repaired: bool = False


def load_golden_questions() -> list[GoldenQuestion]:
    examples = [
        GoldenQuestion(f"example-{index}", example.question, example.answer.sql or "")
        for index, example in enumerate(EXAMPLE_QUESTIONS, start=1)
    ]
    with GOLDEN_FILE.open("rb") as file:
        extra = [GoldenQuestion(**item) for item in tomllib.load(file)["questions"]]
    return examples + extra


def normalize(value: JsonValue) -> JsonValue:
    """One spelling per value, so equal answers compare equal however a model typed them.

    Numbers (including decimal strings) are rounded to two places; midnight
    timestamps become dates, and "2025-10" becomes the month's first day.
    """
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return str(Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP))
    if isinstance(value, str):
        if match := _MIDNIGHT.fullmatch(value):
            return match.group(1)
        if _YEAR_MONTH.fullmatch(value):
            return f"{value}-01"
        try:
            date.fromisoformat(value)
        except ValueError:
            pass
        else:
            return value
        try:
            return str(Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP))
        except InvalidOperation:
            return value
    return value


def results_match(
    expected: Sequence[Sequence[JsonValue]], actual: Sequence[Sequence[JsonValue]]
) -> bool:
    """Whether ``actual`` holds ``expected``'s rows, in any order, in some of its columns.

    Models name and order columns as they like, and may add one (an order
    count beside a revenue), so every way of picking the expected number of
    columns from the actual result is tried.
    """
    if len(expected) != len(actual):
        return False
    if not expected:
        return True
    width = len(expected[0])
    wanted = Counter(tuple(normalize(value) for value in row) for row in expected)
    normalized = [[normalize(value) for value in row] for row in actual]
    for columns in itertools.permutations(range(len(normalized[0])), width):
        if Counter(tuple(row[index] for index in columns) for row in normalized) == wanted:
            return True
    return False


def evaluate(
    app: Flask,
    model_ids: Sequence[str],
    questions: Sequence[GoldenQuestion],
    *,
    delay_seconds: float,
    on_outcome: Callable[[Outcome], None] = lambda _outcome: None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Outcome]:
    """Ask every question of every model; nothing it writes to the database is kept."""
    outcomes: list[Outcome] = []
    with app.app_context():
        settings = current_settings()
        executor = ReadonlyExecutor(
            get_readonly_engine(), statement_timeout_ms=settings.ai_statement_timeout_ms
        )

        def reference(question: GoldenQuestion) -> list[list[JsonValue]]:
            guarded = guard_sql(question.sql, max_rows=settings.ai_max_rows)
            return executor.run(guarded).rows

        config = RegistryConfig.load(settings.llm_models_file or DEFAULT_REGISTRY_FILE)
        connection = db.engine.connect()
        outer = connection.begin()
        # The service commits its audit rows; joined like this, each commit
        # only releases a savepoint, and the rollback below discards them all.
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            # A hash no password matches: this user can never log in, and the
            # rollback removes it anyway.
            user = User(
                email="ask-evaluation@datapilot.dev",
                full_name="Evaluation",
                password_hash="!",  # noqa: S106
            )
            session.add(user)
            session.flush()
            schema = describe_analytics_views(session)
            services: dict[str, AskService] = {}
            for model_id in model_ids:
                # No fallbacks: each model is measured on its own.
                registry = ModelRegistry(
                    config, api_keys=settings.llm_api_keys, default_model=model_id
                )
                client = create_llm_client(
                    registry.resolve(model_id),
                    timeout_seconds=settings.llm_timeout_seconds,
                    max_output_tokens=settings.llm_max_output_tokens,
                )
                services[model_id] = _service(session, registry, client, executor, schema)
            # Question by question, every model in turn: consecutive requests
            # to one model are then several delays apart, which keeps free
            # tiers' per-minute limits out of the results.
            for question in questions:
                for model_id, service in services.items():
                    outcome = ask_and_grade(service, user.id, model_id, question, reference)
                    outcomes.append(outcome)
                    on_outcome(outcome)
                    sleep(delay_seconds)
        finally:
            session.close()
            outer.rollback()
            connection.close()
    return outcomes


def _service(
    session: Session,
    registry: ModelRegistry,
    client: LLMClient,
    executor: ReadonlyExecutor,
    schema: str,
) -> AskService:
    settings = current_settings()
    return AskService(
        session,
        registry=registry,
        client_for=lambda _model: client,
        runner=executor,
        # The per-user limit protects the API, not the evaluation; --delay
        # paces the requests to the provider instead.
        rate_limiter=FixedWindowRateLimiter(
            get_redis(), name="ai-evaluation", limit=1_000_000, window_seconds=60
        ),
        describe_schema=lambda: schema,
        max_rows=settings.ai_max_rows,
        statement_timeout_ms=settings.ai_statement_timeout_ms,
    )


def ask_and_grade(
    service: AskService,
    user_id: int,
    model_id: str,
    question: GoldenQuestion,
    reference: Callable[[GoldenQuestion], list[list[JsonValue]]],
) -> Outcome:
    # Questions like "the last 90 days" are relative to now(), so the right
    # answer drifts while a run goes on. The reference runs just before and
    # just after the model's query; matching either counts.
    before = reference(question)
    started = time.perf_counter()
    try:
        answer = service.ask(user_id, question.question, model_id)
    except AppError as error:
        return Outcome(model_id, question.id, error.code, _elapsed_ms(started))
    latency_ms = _elapsed_ms(started)
    rows = answer.result.rows
    correct = results_match(before, rows) or results_match(reference(question), rows)
    result = CORRECT if correct else WRONG_RESULT
    return Outcome(model_id, question.id, result, latency_ms, answer.repaired)


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def models_to_evaluate(enabled: Mapping[str, RegisteredModel], requested: str | None) -> list[str]:
    """The models named in ``requested``, or else every enabled one not marked to skip."""
    if requested:
        return [model_id.strip() for model_id in requested.split(",") if model_id.strip()]
    return [model.id for model in enabled.values() if model.skip_evaluation is None]


def render_report(
    outcomes: Sequence[Outcome],
    models: Sequence[RegisteredModel],
    questions: Sequence[GoldenQuestion],
    *,
    generated_on: date,
    orders: int,
    skipped: Sequence[RegisteredModel] = (),
) -> str:
    """The Markdown comparison: one row per model, then one row per question.

    ``skipped`` are enabled models left out of the run; each with a
    ``skip_evaluation`` reason gets a line saying why.
    """
    lines = [
        "# Ask your data: model evaluation",
        "",
        f"Generated by `make eval-ask` on {generated_on.isoformat()}, against a dataset of "
        f"{orders:,} orders, with prompt version `{PROMPT_VERSION}`.",
        "",
        f"Each model answered the same {len(questions)} golden questions through the "
        "production pipeline (prompt, SQL guard, read-only role, one repair), without "
        "fallback to another model. A question passes when the result has the same rows as "
        "the reference SQL, in any order (numbers compared at two decimal places). The "
        "questions and reference SQL are in `backend/app/ai/examples.py` and "
        "`backend/scripts/golden_questions.toml`.",
        "",
        "| Model | Provider | Passed | Pass rate | Answered | Correct when answered "
        "| Median latency | Repaired | Failures by type |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for model in models:
        mine = [outcome for outcome in outcomes if outcome.model == model.id]
        passed = sum(outcome.result == CORRECT for outcome in mine)
        answered = sum(outcome.result not in PROVIDER_FAILURES for outcome in mine)
        failures = Counter(outcome.result for outcome in mine if outcome.result != CORRECT)
        failure_text = ", ".join(f"{kind} {count}" for kind, count in sorted(failures.items()))
        median = statistics.median(outcome.latency_ms for outcome in mine) if mine else 0
        lines.append(
            f"| {model.label} (`{model.id}`) | {model.provider.label} | {passed}/{len(mine)} "
            f"| {_percent(passed, len(mine))} | {answered}/{len(mine)} "
            f"| {_percent(passed, answered)} | {median / 1000:.1f} s "
            f"| {sum(o.repaired for o in mine)} | {failure_text or 'none'} |"
        )
    lines += [
        "",
        "Latency is the full time per question, model and database included, with any "
        "format retry and repair. Failure types are the API's error codes, plus "
        "`wrong_result` for an answer whose rows differ from the reference. "
        "`llm_rate_limited` and `llm_unavailable` mean the provider did not answer at all: "
        "on free tiers they measure the day's quota, not the model, so \"Correct when "
        'answered" leaves them out.',
    ]
    notes = [model for model in skipped if model.skip_evaluation]
    if notes:
        lines += ["", "Not in this run:", ""]
        lines += [f"- {model.label} (`{model.id}`): {model.skip_evaluation}" for model in notes]
    lines += [
        "",
        "## Results by question",
        "",
        "| Question | " + " | ".join(f"`{model.id}`" for model in models) + " |",
        "| --- | " + " | ".join("---" for _ in models) + " |",
    ]
    by_key = {(outcome.model, outcome.question): outcome for outcome in outcomes}
    for question in questions:
        cells = [_cell(by_key.get((model.id, question.id))) for model in models]
        lines.append(f"| {question.question} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Running it",
        "",
        "Set the API key of at least one provider in `.env` (see `.env.example`), load a "
        "dataset (`make seed` or `make seed scale=full`), then run `make eval-ask`. It asks "
        "every enabled model whose registry entry has no `skip_evaluation` reason, and "
        "rewrites this file. To include another model, name the models: "
        '`make eval-ask args="--models groq-gpt-oss-120b,gemini-3.5-flash"`.',
        "",
    ]
    return "\n".join(lines)


def _percent(part: int, whole: int) -> str:
    return f"{part / whole:.0%}" if whole else "n/a"


def _cell(outcome: Outcome | None) -> str:
    if outcome is None:
        return "not run"
    return outcome.result + (" (repaired)" if outcome.repaired else "")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--models",
        help="Comma-separated model ids; default: every enabled model without skip_evaluation.",
    )
    parser.add_argument(
        "--delay", type=float, default=3.0, help="Seconds between questions (free-tier limits)."
    )
    parser.add_argument(
        "--output", type=Path, default=REPORT_FILE, help="Where to write the report."
    )
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        enabled = {model.id: model for model in get_model_registry().enabled_models}
        orders = db.session.scalar(select(func.count()).select_from(Order)) or 0
    chosen = models_to_evaluate(enabled, args.models)
    unknown = [model_id for model_id in chosen if model_id not in enabled]
    if unknown or not chosen:
        sys.exit(
            "No enabled model to evaluate. Set a provider's API key in .env (GROQ_API_KEY, "
            "GEMINI_API_KEY, OPENROUTER_API_KEY or ANTHROPIC_API_KEY)"
            + (f"; not enabled: {', '.join(unknown)}" if unknown else "")
            + "."
        )

    questions = load_golden_questions()
    print(f"Asking {len(questions)} questions of {', '.join(chosen)}.", file=sys.stderr)
    outcomes = evaluate(
        app,
        chosen,
        questions,
        delay_seconds=args.delay,
        on_outcome=lambda outcome: print(
            f"  {outcome.model:<28} {outcome.result:<22} {outcome.latency_ms:>6} ms  "
            f"{outcome.question}",
            file=sys.stderr,
        ),
    )
    report = render_report(
        outcomes,
        [enabled[model_id] for model_id in chosen],
        questions,
        generated_on=date.today(),
        orders=orders,
        skipped=[model for model in enabled.values() if model.id not in chosen],
    )
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
