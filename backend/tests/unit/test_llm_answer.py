import json

import pytest

from app.ai.answer import (
    ANSWER_JSON_SCHEMA,
    MAX_ASSUMPTIONS,
    MAX_EXPLANATION_LENGTH,
    InvalidAnswerError,
    LLMAnswer,
    parse_answer,
)

ANSWER = {
    "sql": "SELECT channel, count(*) FROM v_orders GROUP BY channel ORDER BY 2 DESC",
    "explanation": "Orders per channel.",
    "chart": "bar",
    "assumptions": ["Counts every status."],
}
ANSWER_JSON = json.dumps(ANSWER)


@pytest.mark.parametrize(
    "reply",
    [
        ANSWER_JSON,
        f"```json\n{ANSWER_JSON}\n```",
        f"Here is the query you asked for:\n\n{ANSWER_JSON}\n\nLet me know if you need more.",
        f'<think>The user wants {{counts}} per channel. Maybe {{"a": 1}}?</think>\n{ANSWER_JSON}',
        # Another JSON object before the answer is skipped.
        f'Result shape: {{"channel": "web", "count": 1}}. Answer: {ANSWER_JSON}',
    ],
)
def test_parse_answer_finds_the_answer_object_in_any_reply_shape(reply: str) -> None:
    assert parse_answer(reply) == LLMAnswer.model_validate(ANSWER)


def test_parse_answer_keeps_braces_inside_strings() -> None:
    answer = ANSWER | {"sql": "SELECT '{not json}' AS text FROM v_orders ORDER BY 1"}

    assert parse_answer(json.dumps(answer)).sql == answer["sql"]


def test_parse_answer_reads_a_null_or_blank_sql_as_unanswerable() -> None:
    for sql in (None, "", "   "):
        answer = parse_answer(json.dumps(ANSWER | {"sql": sql, "chart": "none"}))
        assert answer.sql is None


def test_parse_answer_ignores_extra_keys_and_trims_the_explanation() -> None:
    answer = parse_answer(json.dumps(ANSWER | {"confidence": 0.9, "explanation": "  Orders.  "}))

    assert answer.explanation == "Orders."
    assert answer.assumptions == ["Counts every status."]


def test_parse_answer_allows_missing_assumptions() -> None:
    data = {key: value for key, value in ANSWER.items() if key != "assumptions"}

    assert parse_answer(json.dumps(data)).assumptions == []


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        ("", "does not contain the JSON answer object"),
        ("SELECT 1", "does not contain the JSON answer object"),
        ('{"sql": "SELECT 1", "explanation": "x", "chart": "pie"', "does not contain"),
        ('{"result": 1}', "does not contain the JSON answer object"),
        (json.dumps(ANSWER | {"chart": "pie"}), "chart: Input should be 'none', 'bar' or 'line'"),
        (json.dumps({"sql": "SELECT 1"}), "explanation: Field required"),
        (json.dumps(ANSWER | {"explanation": ""}), "explanation: String should have at least"),
        (
            json.dumps(ANSWER | {"explanation": "x" * (MAX_EXPLANATION_LENGTH + 1)}),
            "explanation: String should have at most",
        ),
        (
            json.dumps(ANSWER | {"assumptions": ["a"] * (MAX_ASSUMPTIONS + 1)}),
            "assumptions: List should have at most",
        ),
        (json.dumps(ANSWER | {"sql": 42}), "sql: Input should be a valid string"),
    ],
)
def test_parse_answer_explains_what_is_wrong_for_the_retry(reply: str, problem: str) -> None:
    with pytest.raises(InvalidAnswerError, match=problem):
        parse_answer(reply)


def test_validation_messages_never_echo_the_reply() -> None:
    reply = json.dumps(ANSWER | {"chart": "IGNORE-PREVIOUS-INSTRUCTIONS"})

    with pytest.raises(InvalidAnswerError) as caught:
        parse_answer(reply)

    assert "IGNORE-PREVIOUS-INSTRUCTIONS" not in str(caught.value)


def test_answer_json_schema_matches_the_answer_model() -> None:
    assert set(ANSWER_JSON_SCHEMA["required"]) == set(LLMAnswer.model_fields)
    assert set(ANSWER_JSON_SCHEMA["properties"]) == set(LLMAnswer.model_fields)
    assert ANSWER_JSON_SCHEMA["additionalProperties"] is False
