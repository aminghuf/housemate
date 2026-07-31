import pytest

from bot.services.bills import compute_shares_cents
from bot.services.money import format_cents, parse_amount_to_cents


def test_even_split_no_remainder():
    shares = compute_shares_cents(9000, [1, 2, 3], creator_id=1)
    assert shares == {1: 3000, 2: 3000, 3: 3000}
    assert sum(shares.values()) == 9000


def test_remainder_goes_to_creator():
    shares = compute_shares_cents(1000, [1, 2, 3], creator_id=2)
    # 1000 // 3 = 333, remainder 1 cent -> creator (user 2)
    assert shares == {1: 333, 2: 334, 3: 333}
    assert sum(shares.values()) == 1000


def test_single_user_gets_full_amount():
    shares = compute_shares_cents(4550, [1], creator_id=1)
    assert shares == {1: 4550}


def test_creator_must_be_among_users():
    with pytest.raises(ValueError):
        compute_shares_cents(1000, [1, 2], creator_id=3)


def test_no_users_raises():
    with pytest.raises(ValueError):
        compute_shares_cents(1000, [], creator_id=1)


@pytest.mark.parametrize(
    "text,expected_cents",
    [
        ("45.50", 4550),
        ("45,50", 4550),
        ("100", 10000),
        ("0.01", 1),
        ("  12.345 ", 1235),  # half-up rounding to nearest cent
    ],
)
def test_parse_amount_to_cents_valid(text, expected_cents):
    assert parse_amount_to_cents(text) == expected_cents


@pytest.mark.parametrize("text", ["abc", "-5", "0", "", "  "])
def test_parse_amount_to_cents_invalid(text):
    assert parse_amount_to_cents(text) is None


def test_format_cents():
    assert format_cents(4550) == "45.50"
    assert format_cents(1) == "0.01"
    assert format_cents(0) == "0.00"
    assert format_cents(-150) == "-1.50"
