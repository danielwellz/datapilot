"""The demo model: deterministic, offline, and limited to the example questions.

It lets anyone try Ask your data without an API key, and lets tests run the
whole pipeline without a network. Its answers go through the same guard,
read-only role and audit as any real model's.
"""

import html
import re

from app.ai.answer import LLMAnswer
from app.ai.clients.base import LLMResult, TokenUsage
from app.ai.examples import EXAMPLE_QUESTIONS, ExampleQuestion, normalize_question
from app.ai.prompt import Prompt

UNKNOWN_QUESTION_EXPLANATION = (
    "The demo model only answers the example questions. Pick one of them, or set an API key "
    "for one of the providers to ask your own questions."
)

_QUESTION = re.compile(r"<question>\n(.*)\n</question>", re.DOTALL)


class FakeLLMClient:
    def __init__(self, examples: tuple[ExampleQuestion, ...] = EXAMPLE_QUESTIONS) -> None:
        self._answers: dict[str, LLMAnswer] = {}
        for example in examples:
            for phrasing in (example.question, *example.variants):
                self._answers[normalize_question(phrasing)] = example.answer

    def answer(self, prompt: Prompt) -> LLMResult:
        question = _last_question(prompt)
        answer = self._answers.get(normalize_question(question)) or LLMAnswer(
            sql=None, explanation=UNKNOWN_QUESTION_EXPLANATION, chart="none"
        )
        return LLMResult(answer, TokenUsage())


def _last_question(prompt: Prompt) -> str:
    # The question is the last <question> turn; a repair request comes after it.
    for message in reversed(prompt.messages):
        match = _QUESTION.fullmatch(message.content) if message.role == "user" else None
        if match:
            return html.unescape(match.group(1))
    return ""
