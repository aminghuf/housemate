"""Money helpers. All amounts are stored/passed around as integer cents to
avoid floating-point rounding drift — only converted to/from Decimal at the
edges (parsing user input, formatting for display)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def parse_amount_to_cents(text: str) -> int | None:
    cleaned = text.strip().replace(",", ".")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"
