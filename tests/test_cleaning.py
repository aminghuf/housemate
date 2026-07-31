import datetime as dt
from dataclasses import dataclass

import pytest

from bot.services.cleaning import BATHROOM, HALL, KITCHEN, assign_sections, next_cleaning_day


@dataclass
class FakeRow:
    user_id: int


def test_assign_sections_three_housemates_gets_one_each():
    queue = [FakeRow(1), FakeRow(2), FakeRow(3)]
    assignments = assign_sections(queue, 0)
    assert assignments[KITCHEN].user_id == 1
    assert assignments[HALL].user_id == 2
    assert assignments[BATHROOM].user_id == 3


def test_assign_sections_wraps_with_position_offset():
    queue = [FakeRow(1), FakeRow(2), FakeRow(3)]
    assignments = assign_sections(queue, 2)
    assert assignments[KITCHEN].user_id == 3
    assert assignments[HALL].user_id == 1
    assert assignments[BATHROOM].user_id == 2


def test_assign_sections_two_housemates_one_gets_two_sections():
    queue = [FakeRow(1), FakeRow(2)]
    assignments = assign_sections(queue, 0)
    assert assignments[KITCHEN].user_id == 1
    assert assignments[HALL].user_id == 2
    assert assignments[BATHROOM].user_id == 1  # wraps back around


def test_assign_sections_one_housemate_gets_all_three():
    queue = [FakeRow(1)]
    assignments = assign_sections(queue, 0)
    assert assignments[KITCHEN].user_id == 1
    assert assignments[HALL].user_id == 1
    assert assignments[BATHROOM].user_id == 1


@pytest.mark.parametrize(
    "today,expected",
    [
        (dt.date(2026, 8, 1), dt.date(2026, 8, 2)),  # Saturday reminder run -> tomorrow's Sunday
        (dt.date(2026, 8, 2), dt.date(2026, 8, 2)),  # today already Sunday
        (dt.date(2026, 7, 27), dt.date(2026, 8, 2)),  # Monday -> upcoming Sunday
    ],
)
def test_next_cleaning_day(today, expected):
    assert next_cleaning_day(today) == expected
