from flask import Flask
from sqlalchemy import func, select
from sqlalchemy.orm import Session, scoped_session

from app.ai.examples import EXAMPLE_QUESTIONS
from app.models import AiQuery, User
from scripts.eval_ask import evaluate, load_golden_questions


def test_evaluation_asks_every_question_and_keeps_nothing(
    app: Flask, db_session: scoped_session[Session]
) -> None:
    questions = load_golden_questions()
    sleeps: list[float] = []

    outcomes = evaluate(app, ["fake"], questions, delay_seconds=0.25, sleep=sleeps.append)

    results = [outcome.result for outcome in outcomes]
    # The demo model knows the examples and nothing else.
    assert results == ["pass"] * len(EXAMPLE_QUESTIONS) + ["question_unanswerable"] * 7
    assert sleeps == [0.25] * len(questions)
    count = select(func.count()).select_from
    assert db_session.scalar(count(AiQuery)) == 0
    assert (
        db_session.scalar(select(func.count()).where(User.email.startswith("ask-evaluation"))) == 0
    )
