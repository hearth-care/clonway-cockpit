"""England & Wales bank holidays and business-day utilities.

Extracted from Auto-Bookkeeper ``src/xbook/calendar/bank_holidays.py`` (97
lines, hardcoded 2024–2027 table) and centralised here so any worker that
schedules around payment / working days can import a single source.

Data: England & Wales public holidays sourced from gov.uk.
Table last verified: 2026-06-11 against
  https://www.gov.uk/bank-holidays.json  (England and Wales division)
Covers 2024-01-01 through 2028-12-31.

IMPORTANT — refresh discipline
-------------------------------
:data:`DATA_HORIZON` is the last 31 December covered by this table.
Querying a date beyond ``DATA_HORIZON`` raises :exc:`BankHolidayHorizonError`
so callers never get a silent "not a holiday" for a date the table cannot answer.

The unit test in ``tests/test_uk_calendar.py`` (CC-CAL-FRESH-1) fails when
``DATA_HORIZON - today < 12 months``, so this repo's CI becomes the annual
refresh reminder. Fix: add the next year's data and bump ``DATA_HORIZON``.
"""

from __future__ import annotations

from datetime import date, timedelta

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class BankHolidayHorizonError(ValueError):
    """Raised when a date query is beyond the loaded bank-holiday table."""


# ---------------------------------------------------------------------------
# Bank-holiday data — England & Wales
# Table verified 2026-06-11 against gov.uk  (public repo: no internal IDs)
# ---------------------------------------------------------------------------

_BANK_HOLIDAYS: frozenset[date] = frozenset(
    [
        # 2024
        date(2024, 1, 1),  # New Year's Day
        date(2024, 3, 29),  # Good Friday
        date(2024, 4, 1),  # Easter Monday
        date(2024, 5, 6),  # Early May bank holiday
        date(2024, 5, 27),  # Spring bank holiday
        date(2024, 8, 26),  # Summer bank holiday
        date(2024, 12, 25),  # Christmas Day
        date(2024, 12, 26),  # Boxing Day
        # 2025
        date(2025, 1, 1),  # New Year's Day
        date(2025, 4, 18),  # Good Friday
        date(2025, 4, 21),  # Easter Monday
        date(2025, 5, 5),  # Early May bank holiday
        date(2025, 5, 26),  # Spring bank holiday
        date(2025, 8, 25),  # Summer bank holiday
        date(2025, 12, 25),  # Christmas Day
        date(2025, 12, 26),  # Boxing Day
        # 2026
        date(2026, 1, 1),  # New Year's Day
        date(2026, 4, 3),  # Good Friday
        date(2026, 4, 6),  # Easter Monday
        date(2026, 5, 4),  # Early May bank holiday
        date(2026, 5, 25),  # Spring bank holiday
        date(2026, 8, 31),  # Summer bank holiday
        date(2026, 12, 25),  # Christmas Day
        date(2026, 12, 28),  # Boxing Day (substitute — 26th is Saturday)
        # 2027
        date(2027, 1, 1),  # New Year's Day
        date(2027, 3, 26),  # Good Friday
        date(2027, 3, 29),  # Easter Monday
        date(2027, 5, 3),  # Early May bank holiday
        date(2027, 5, 31),  # Spring bank holiday
        date(2027, 8, 30),  # Summer bank holiday
        date(2027, 12, 27),  # Christmas Day (substitute — 25th is Saturday)
        date(2027, 12, 28),  # Boxing Day (substitute — 26th is Sunday)
        # 2028
        date(2028, 1, 3),  # New Year's Day (substitute — 1st is Saturday)
        date(2028, 4, 14),  # Good Friday
        date(2028, 4, 17),  # Easter Monday
        date(2028, 5, 1),  # Early May bank holiday
        date(2028, 5, 29),  # Spring bank holiday
        date(2028, 8, 28),  # Summer bank holiday
        date(2028, 12, 25),  # Christmas Day
        date(2028, 12, 26),  # Boxing Day
    ]
)

DATA_HORIZON: date = date(2028, 12, 31)
"""Last calendar day fully covered by the bank-holiday table."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _check_horizon(d: date) -> None:
    if d > DATA_HORIZON:
        raise BankHolidayHorizonError(
            f"{d} is beyond DATA_HORIZON ({DATA_HORIZON}). "
            "Update clonway_cockpit.uk_calendar with the next year's bank-holiday data."
        )


def is_bank_holiday(d: date) -> bool:
    """Return ``True`` if ``d`` is an England & Wales bank holiday.

    Raises :exc:`BankHolidayHorizonError` for dates after :data:`DATA_HORIZON`.
    """
    _check_horizon(d)
    return d in _BANK_HOLIDAYS


def is_business_day(d: date) -> bool:
    """Return ``True`` if ``d`` is a weekday that is not a bank holiday.

    Raises :exc:`BankHolidayHorizonError` for dates after :data:`DATA_HORIZON`.
    """
    _check_horizon(d)
    return d.weekday() < 5 and d not in _BANK_HOLIDAYS


def next_business_day(d: date) -> date:
    """Return the next business day on or after ``d`` (idempotent if ``d`` already is one).

    Raises :exc:`BankHolidayHorizonError` if any candidate date is after
    :data:`DATA_HORIZON`.
    """
    _check_horizon(d)
    while not is_business_day(d):
        d += timedelta(days=1)
        _check_horizon(d)
    return d


def previous_business_day(d: date) -> date:
    """Return the most recent business day on or before ``d``.

    Raises :exc:`BankHolidayHorizonError` if the starting date ``d`` is after
    :data:`DATA_HORIZON`.
    """
    _check_horizon(d)
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def business_days_between(a: date, b: date) -> int:
    """Return the count of business days in the half-open interval ``[a, b)``.

    Returns a negative number if ``a > b`` (counts backwards).
    Raises :exc:`BankHolidayHorizonError` for any date beyond :data:`DATA_HORIZON`.
    """
    if a > b:
        return -business_days_between(b, a)
    _check_horizon(b)
    count = 0
    current = a
    while current < b:
        _check_horizon(current)
        if is_business_day(current):
            count += 1
        current += timedelta(days=1)
    return count


def horizon_needs_refresh(today: date, *, lead: timedelta = timedelta(days=180)) -> bool:
    """Return ``True`` when the table horizon is within ``lead`` days of ``today``.

    Default lead is 180 days (≈ 6 months). Worker Doctor screens and
    ``scan_horizon()`` checks can use this to raise an operator signal before
    the cliff, turning the "refresh annually" comment into an observable.
    """
    return (DATA_HORIZON - today) <= lead
