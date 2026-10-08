"""The answer logic shared by every text-returning client, and the demo model."""

import json

import pytest

from app.ai.answer import LLMAnswer
from app.ai.clients.base import (
    InvalidModelOutputError,
    ProviderError,
    ProviderFailure,
    Reply,
    TextReplyClient,
    TokenUsage,
)
from app.ai.clients.fake import UNKNOWN_QUESTION_EXPLANATION, FakeLLMClient
from app.ai.examples import EXAMPLE_QUESTIONS, ExampleQuestion
from app.ai.prompt import ChatMessage, Prompt, build_prompt, repair_request

VALID = json.dumps({"sql": "SELECT 1", "explanation": "One.", "chart": "none", "assumptions": []})


class ScriptedClient(TextReplyClient):
    """Returns prepared replies in order and records every prompt it was sent."""

    def __init__(self, *replies: Reply | ProviderError) -> None:
        super().__init__(sleep=lambda _seconds: None)
        self._replies = list(replies)
        self.prompts: list[Prompt] = []

    def send(self, prompt: Prompt) -> Reply:
        self.prompts.append(prompt)
        reply = self._replies.pop(0)
        if isinstance(reply, ProviderError):
            raise reply
        return reply


def _reply(text: str, *, refused: bool = False) -> Reply:
    return Reply(text, TokenUsage(input_tokens=100, output_tokens=10), refused=refused)


PROMPT = build_prompt("How many orders?", "schema")


def test_a_valid_reply_is_answered_with_one_request() -> None:
    client = ScriptedClient(_reply(VALID))

    result = client.answer(PROMPT)

    assert result.answer.sql == "SELECT 1"
    assert result.usage == TokenUsage(100, 10)
    assert len(client.prompts) == 1


def test_an_invalid_reply_is_retried_once_with_the_problem() -> None:
    client = ScriptedClient(_reply("Sure! SELECT 1"), _reply(VALID))

    result = client.answer(PROMPT)

    assert result.answer.sql == "SELECT 1"
    assert result.usage == TokenUsage(200, 20)
    retry = client.prompts[1]
    assert retry.messages[:-2] == PROMPT.messages
    assert retry.messages[-2] == ChatMessage("assistant", "Sure! SELECT 1")
    assert "does not contain the JSON answer object" in retry.messages[-1].content


def test_a_second_invalid_reply_gives_up_with_the_usage_of_both() -> None:
    client = ScriptedClient(_reply("no"), _reply('{"sql": 1}'))

    with pytest.raises(InvalidModelOutputError) as caught:
        client.answer(PROMPT)

    assert "not a valid answer" in caught.value.problem
    assert caught.value.usage == TokenUsage(200, 20)
    assert len(client.prompts) == 2


@pytest.mark.parametrize(
    "replies",
    [
        [_reply(VALID, refused=True)],
        [_reply("no"), _reply(VALID, refused=True)],
    ],
)
def test_a_refusal_is_invalid_output_whatever_the_text(replies: list[Reply]) -> None:
    with pytest.raises(InvalidModelOutputError, match="declined to answer"):
        ScriptedClient(*replies).answer(PROMPT)


def test_provider_errors_pass_through_for_the_service_to_fall_back() -> None:
    error = ProviderError(ProviderFailure.RATE_LIMITED, retry_after=30)

    with pytest.raises(ProviderError) as caught:
        ScriptedClient(error).answer(PROMPT)

    assert caught.value.failure is ProviderFailure.RATE_LIMITED
    assert caught.value.retry_after == 30


def test_token_usage_adds_up_and_keeps_unknown_as_none() -> None:
    assert TokenUsage(1, None) + TokenUsage(2, None) == TokenUsage(3, None)
    assert TokenUsage(None, 5) + TokenUsage(4, None) == TokenUsage(4, 5)


def test_the_send_method_must_be_implemented() -> None:
    with pytest.raises(NotImplementedError):
        TextReplyClient().answer(PROMPT)


@pytest.mark.parametrize(
    ("phrasing", "example"),
    [
        (phrasing, example)
        for example in EXAMPLE_QUESTIONS
        for phrasing in (example.question, *example.variants)
    ],
)
def test_fake_client_answers_every_example_question_and_variant(
    phrasing: str, example: ExampleQuestion
) -> None:
    result = FakeLLMClient().answer(build_prompt(phrasing, "schema"))

    assert result.answer == example.answer
    assert result.usage == TokenUsage()


def test_fake_client_ignores_case_punctuation_and_spacing() -> None:
    question = "  what WAS the monthly revenue, over the last 12 months!!  "

    answer = FakeLLMClient().answer(build_prompt(question, "schema")).answer

    assert answer == EXAMPLE_QUESTIONS[0].answer


def test_fake_client_explains_that_it_only_knows_the_examples() -> None:
    answer = FakeLLMClient().answer(build_prompt("Which customers churned?", "schema")).answer

    assert answer == LLMAnswer(sql=None, explanation=UNKNOWN_QUESTION_EXPLANATION, chart="none")


def test_fake_client_reads_the_question_through_escaping_and_later_turns() -> None:
    example = EXAMPLE_QUESTIONS[0]
    fake = FakeLLMClient((ExampleQuestion("Revenue <by> month & year?", example.answer),))
    prompt = build_prompt("Revenue <by> month & year?", "schema")
    prompt = prompt.followed_by(*repair_request(example.answer, "some error"))

    assert fake.answer(prompt).answer == example.answer


def test_fake_client_without_a_question_turn_does_not_answer() -> None:
    answer = FakeLLMClient().answer(Prompt("system", (ChatMessage("user", "hello"),))).answer

    assert answer.sql is None
