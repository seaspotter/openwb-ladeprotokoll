from datetime import datetime, time

from app.scheduler import _next_run_at, _parse_time


def test_parse_time():
    assert _parse_time("00:05") == time(0, 5)
    assert _parse_time("23:59") == time(23, 59)


def test_next_run_at_later_today():
    now = datetime(2026, 9, 4, 10, 0)
    target = time(23, 0)
    assert _next_run_at(target, now) == datetime(2026, 9, 4, 23, 0)


def test_next_run_at_already_passed_today_rolls_to_tomorrow():
    now = datetime(2026, 9, 4, 10, 0)
    target = time(0, 5)
    assert _next_run_at(target, now) == datetime(2026, 9, 5, 0, 5)


def test_next_run_at_exactly_now_rolls_to_tomorrow():
    now = datetime(2026, 9, 4, 0, 5)
    target = time(0, 5)
    assert _next_run_at(target, now) == datetime(2026, 9, 5, 0, 5)
