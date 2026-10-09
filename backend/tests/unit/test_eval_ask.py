from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import JsonValue, SecretStr

from app.ai.registry import DEFAULT_REGISTRY_FILE, ModelRegistry, RegistryConfig
from app.ai.sql_guard import guard_sql
from app.services.ask import AskService
from scripts.eval_ask import (
    Outcome,
    ask_and_grade,
    load_golden_questions,
    models_to_evaluate,
    normalize,
    render_report,
    results_match,
)


def test_there_are_fifteen_golden_questions_with_guard_valid_reference_sql() -> None:
    questions = load_golden_questions()

    assert len(questions) == 15
    assert len({question.id for question in questions}) == 15
    for question in questions:
        guard_sql(question.sql, max_rows=1000)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, "12.00"),
        (2.236, "2.24"),
        ("1234.5", "1234.50"),
        ("0.005", "0.01"),
        ("2025-10-01T00:00:00Z", "2025-10-01"),
        ("2025-10-01T00:00:00+00:00", "2025-10-01"),
        ("2025-10", "2025-10-01"),
        ("2025-10-01", "2025-10-01"),
        ("2025-10-01T12:30:00Z", "2025-10-01T12:30:00Z"),
        ("US", "US"),
        ("Home & Kitchen", "Home & Kitchen"),
        (True, True),
        (None, None),
    ],
)
def test_normalize_gives_one_spelling_per_value(value: object, expected: object) -> None:
    assert normalize(value) == expected  # type: ignore[arg-type]


EXPECTED = [["US", "100.00"], ["DE", "50.50"]]


@pytest.mark.parametrize(
    "actual",
    [
        [["US", "100.00"], ["DE", "50.50"]],
        [["DE", "50.5"], ["US", 100]],
        [["100.00", "US"], ["50.50", "DE"]],
        [["US", 3, "100.00"], ["DE", 2, "50.50"]],
    ],
    ids=["same", "reordered-rows-and-spelling", "swapped-columns", "extra-column"],
)
def test_results_match_whatever_the_order_and_column_layout(actual: list[list[object]]) -> None:
    assert results_match(EXPECTED, actual)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "actual",
    [
        [["US", "100.00"]],
        [["US", "100.00"], ["DE", "50.49"]],
        [["US", "100.00"], ["FR", "50.50"]],
        [["US"], ["DE"]],
    ],
    ids=["missing-row", "wrong-value", "wrong-label", "missing-column"],
)
def test_results_differ_when_a_row_or_value_does(actual: list[list[object]]) -> None:
    assert not results_match(EXPECTED, actual)  # type: ignore[arg-type]


def test_empty_results_match_only_each_other() -> None:
    assert results_match([], [])
    assert not results_match([], [["x"]])


def test_report_compares_models_and_lists_every_question() -> None:
    config = RegistryConfig.load(DEFAULT_REGISTRY_FILE)
    registry = ModelRegistry(config, api_keys={"GROQ_API_KEY": SecretStr("k")})
    model = registry.resolve("groq-gpt-oss-120b")
    questions = load_golden_questions()[:3]
    outcomes = [
        Outcome(model.id, questions[0].id, "pass", 1200),
        Outcome(model.id, questions[1].id, "pass", 3400, repaired=True),
        Outcome(model.id, questions[2].id, "llm_rate_limited", 900),
    ]

    report = render_report(
        outcomes, [model], questions, generated_on=date(2026, 10, 8), orders=2_000_000
    )

    assert "on 2026-10-08, against a dataset of 2,000,000 orders" in report
    assert (
        "| GPT-OSS 120B (Groq) (`groq-gpt-oss-120b`) | Groq | 2/3 | 67% | 2/3 | 100% "
        "| 1.2 s | 1 | llm_rate_limited 1 |" in report
    )
    assert f"| {questions[1].question} | pass (repaired) |" in report
    assert f"| {questions[2].question} | llm_rate_limited |" in report


def test_report_shows_no_rate_when_a_model_never_answered() -> None:
    config = RegistryConfig.load(DEFAULT_REGISTRY_FILE)
    model = ModelRegistry(config, api_keys={"GEMINI_API_KEY": SecretStr("k")}).resolve(
        "gemini-3.5-flash"
    )
    question = load_golden_questions()[0]

    report = render_report(
        [Outcome(model.id, question.id, "llm_rate_limited", 300)],
        [model],
        [question],
        generated_on=date(2026, 10, 8),
        orders=10,
    )

    assert "| 0/1 | 0% | 0/1 | n/a |" in report


class StubService:
    """Answers every question with fixed rows, as AskService would."""

    def __init__(self, rows: list[list[object]]) -> None:
        self._rows = rows

    def ask(self, _user_id: int, _question: str, _model_id: str) -> SimpleNamespace:
        return SimpleNamespace(result=SimpleNamespace(rows=self._rows), repaired=False)


def test_an_answer_matching_the_reference_after_it_drifted_still_passes() -> None:
    # "The last 90 days" moves with the clock: the reference taken after the
    # model's query can differ from the one taken before it.
    taken: list[list[list[JsonValue]]] = [[["US", "100.00"]], [["US", "101.00"]]]
    references = iter(taken)
    question = load_golden_questions()[2]

    outcome = ask_and_grade(
        cast(AskService, StubService([["US", "101.00"]])),
        1,
        "groq-gpt-oss-120b",
        question,
        lambda _question: next(references),
    )

    assert outcome.result == "pass"


def test_an_answer_matching_neither_reference_is_a_wrong_result() -> None:
    question = load_golden_questions()[2]

    outcome = ask_and_grade(
        cast(AskService, StubService([["US", "99.00"]])),
        1,
        "groq-gpt-oss-120b",
        question,
        lambda _question: [["US", "100.00"]],
    )

    assert outcome.result == "wrong_result"


def _shipped_registry() -> ModelRegistry:
    keys = {"GROQ_API_KEY": SecretStr("k"), "GEMINI_API_KEY": SecretStr("k")}
    return ModelRegistry(RegistryConfig.load(DEFAULT_REGISTRY_FILE), api_keys=keys)


def test_the_default_run_leaves_out_models_marked_to_skip() -> None:
    enabled = {model.id: model for model in _shipped_registry().enabled_models}

    assert models_to_evaluate(enabled, None) == [
        "groq-gpt-oss-120b",
        "gemini-3.5-flash-lite",
        "groq-qwen3.8-27b",
    ]


def test_named_models_are_evaluated_even_when_marked_to_skip() -> None:
    enabled = {model.id: model for model in _shipped_registry().enabled_models}

    assert models_to_evaluate(enabled, " gemini-3.5-flash, fake ,") == ["gemini-3.5-flash", "fake"]


def test_report_says_why_a_model_was_left_out() -> None:
    registry = _shipped_registry()
    question = load_golden_questions()[0]
    evaluated = registry.resolve("groq-gpt-oss-120b")

    report = render_report(
        [Outcome(evaluated.id, question.id, "pass", 1000)],
        [evaluated],
        [question],
        generated_on=date(2026, 10, 8),
        orders=10,
        skipped=[registry.resolve("gemini-3.5-flash"), registry.resolve("fake")],
    )

    assert (
        "- Gemini 3.5 Flash (`gemini-3.5-flash`): Its free tier allows only 20 requests a day, "
        "fewer than one evaluation run needs." in report
    )
    assert "- Demo model (example questions only) (`fake`): It answers only the example" in report
    assert "`gemini-3.5-flash` |" not in report
