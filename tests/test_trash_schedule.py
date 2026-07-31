import datetime as dt

import pytest

from bot.services.trash_schedule import (
    CARTA_E_CARTONE,
    INDIFFERENZIATO,
    PLASTICA_E_METALLI,
    UMIDO,
    VETRO,
    get_trash_type,
)

# Anchor: Tuesday 2026-06-02, collects Carta e Cartone.
ANCHOR = dt.date(2026, 6, 2)


@pytest.mark.parametrize(
    "date,expected",
    [
        (dt.date(2026, 6, 1), UMIDO),  # Monday
        (dt.date(2026, 6, 3), PLASTICA_E_METALLI),  # Wednesday
        (dt.date(2026, 6, 4), UMIDO),  # Thursday
        (dt.date(2026, 6, 5), INDIFFERENZIATO),  # Friday
        (dt.date(2026, 6, 6), UMIDO),  # Saturday
        (dt.date(2026, 6, 7), None),  # Sunday: no collection
    ],
)
def test_fixed_days(date, expected):
    assert get_trash_type(date, ANCHOR) == expected


def test_tuesday_on_anchor_is_carta():
    assert get_trash_type(ANCHOR, ANCHOR) == CARTA_E_CARTONE


def test_tuesday_one_week_after_anchor_is_vetro():
    assert get_trash_type(ANCHOR + dt.timedelta(days=7), ANCHOR) == VETRO


def test_tuesday_two_weeks_after_anchor_is_carta_again():
    assert get_trash_type(ANCHOR + dt.timedelta(days=14), ANCHOR) == CARTA_E_CARTONE


def test_tuesday_one_week_before_anchor_is_vetro():
    assert get_trash_type(ANCHOR - dt.timedelta(days=7), ANCHOR) == VETRO


def test_tuesday_two_weeks_before_anchor_is_carta():
    assert get_trash_type(ANCHOR - dt.timedelta(days=14), ANCHOR) == CARTA_E_CARTONE
