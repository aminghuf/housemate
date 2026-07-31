"""Pure trash-schedule logic (spec §5.1) — no DB access, easy to unit test.

Fixed weekly collection schedule, with Tuesday alternating between "Carta e
Cartone" and "Vetro" every other Tuesday, anchored to a configurable date
(the first Tuesday the bot went live, defaulting to "Carta e Cartone").
"""
from __future__ import annotations

import datetime as dt

UMIDO = "Umido"
CARTA_E_CARTONE = "Carta e Cartone"
VETRO = "Vetro"
PLASTICA_E_METALLI = "Plastica e Metalli"
INDIFFERENZIATO = "Indifferenziato"

# weekday(): Monday=0 ... Sunday=6
_FIXED_SCHEDULE: dict[int, str] = {
    0: UMIDO,  # Monday
    2: PLASTICA_E_METALLI,  # Wednesday
    3: UMIDO,  # Thursday
    4: INDIFFERENZIATO,  # Friday
    5: UMIDO,  # Saturday
}
TUESDAY = 1
SUNDAY = 6


def get_trash_type(date: dt.date, anchor_date: dt.date) -> str | None:
    """Returns today's trash type, or None if there's no collection (Sunday).

    `anchor_date` must be a Tuesday; the Tuesday it falls on collects
    "Carta e Cartone", alternating every 7 days after/before that.
    """
    weekday = date.weekday()

    if weekday == SUNDAY:
        return None

    if weekday == TUESDAY:
        weeks_since_anchor = (date - anchor_date).days // 7
        return CARTA_E_CARTONE if weeks_since_anchor % 2 == 0 else VETRO

    return _FIXED_SCHEDULE[weekday]
