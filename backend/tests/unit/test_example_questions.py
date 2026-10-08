import pytest
import sqlglot
from sqlglot import exp

from app.ai.examples import EXAMPLE_QUESTIONS, ExampleQuestion, normalize_question
from app.ai.sql_guard import guard_sql


def test_there_are_six_to_eight_example_questions() -> None:
    assert 6 <= len(EXAMPLE_QUESTIONS) <= 8


def test_no_two_phrasings_mean_different_examples() -> None:
    phrasings = [
        normalize_question(phrasing)
        for example in EXAMPLE_QUESTIONS
        for phrasing in (example.question, *example.variants)
    ]

    assert len(phrasings) == len(set(phrasings))


@pytest.mark.parametrize("example", EXAMPLE_QUESTIONS, ids=lambda example: example.question)
def test_example_answers_pass_the_guard_and_fit_their_chart(example: ExampleQuestion) -> None:
    assert example.answer.sql is not None
    guarded = guard_sql(example.answer.sql, max_rows=1000)

    select = sqlglot.parse_one(guarded.sql, read="postgres")
    assert isinstance(select, exp.Select)
    # Bar and line charts plot one label column against one number.
    assert example.answer.chart in ("bar", "line")
    assert len(select.expressions) == 2


def test_normalize_question_ignores_case_punctuation_and_spacing() -> None:
    assert normalize_question("  AOV, by Country?! ") == "aov by country"
