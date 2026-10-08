from datetime import UTC, datetime

from app.clock import utc_today


def test_utc_today_is_the_current_date_in_utc() -> None:
    before = datetime.now(UTC).date()
    today = utc_today()

    assert before <= today <= datetime.now(UTC).date()
