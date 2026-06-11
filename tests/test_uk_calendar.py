# tests/test_uk_calendar.py
"""CC-CAL-* — uk_calendar unit tests.

Fixture dates verified against the xbook bank_holidays.py originals so
existing bookkeeper consumers see no regressions.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from clonway_cockpit.uk_calendar import (
    DATA_HORIZON,
    BankHolidayHorizonError,
    business_days_between,
    horizon_needs_refresh,
    is_bank_holiday,
    is_business_day,
    next_business_day,
    previous_business_day,
)

# ---- known fixture dates (regression-guard vs xbook originals) --------------


def test_early_may_2026_is_bank_holiday():  # CC-CAL-FIX-1
    # 2026 Early May bank holiday
    assert is_bank_holiday(date(2026, 5, 4))


def test_christmas_2024_is_bank_holiday():  # CC-CAL-FIX-2
    assert is_bank_holiday(date(2024, 12, 25))


def test_boxing_day_substitute_2026():  # CC-CAL-FIX-3
    # 26th Dec 2026 is Saturday → substitute 28th Dec
    assert not is_bank_holiday(date(2026, 12, 26))
    assert is_bank_holiday(date(2026, 12, 28))


def test_christmas_substitute_2027():  # CC-CAL-FIX-4
    # 25th Dec 2027 is Saturday → substitute 27th Dec
    assert not is_bank_holiday(date(2027, 12, 25))
    assert is_bank_holiday(date(2027, 12, 27))


def test_good_friday_2025():  # CC-CAL-FIX-5
    assert is_bank_holiday(date(2025, 4, 18))


def test_easter_monday_2025():  # CC-CAL-FIX-6
    assert is_bank_holiday(date(2025, 4, 21))


def test_new_years_day_2028_substitute():  # CC-CAL-FIX-7
    # 1 Jan 2028 is Saturday → substitute 3 Jan
    assert not is_bank_holiday(date(2028, 1, 1))
    assert is_bank_holiday(date(2028, 1, 3))


def test_ordinary_wednesday_not_bank_holiday():  # CC-CAL-FIX-8
    assert not is_bank_holiday(date(2026, 6, 10))


# ---- is_business_day --------------------------------------------------------


def test_weekday_not_holiday_is_business_day():  # CC-CAL-BD-1
    assert is_business_day(date(2026, 6, 10))  # Wednesday


def test_saturday_not_business_day():  # CC-CAL-BD-2
    assert not is_business_day(date(2026, 6, 13))


def test_sunday_not_business_day():  # CC-CAL-BD-3
    assert not is_business_day(date(2026, 6, 14))


def test_bank_holiday_not_business_day():  # CC-CAL-BD-4
    assert not is_business_day(date(2026, 5, 4))  # Early May


# ---- next_business_day ------------------------------------------------------


def test_next_business_day_idempotent_on_business_day():  # CC-CAL-NEXT-1
    d = date(2026, 6, 10)  # Wednesday
    assert next_business_day(d) == d


def test_next_business_day_skips_weekend():  # CC-CAL-NEXT-2
    friday = date(2026, 6, 12)
    assert next_business_day(friday + timedelta(days=1)) == date(2026, 6, 15)


def test_next_business_day_skips_bank_holiday():  # CC-CAL-NEXT-3
    # Day before Early May 2026: Mon 4th is holiday, next BD is Tue 5th
    assert next_business_day(date(2026, 5, 4)) == date(2026, 5, 5)


def test_next_business_day_skips_christmas_cluster_2026():  # CC-CAL-NEXT-4
    # 24 Dec 2026 (Thu) → next BD = 29 Dec (Tue); 25/28 are holidays
    assert next_business_day(date(2026, 12, 24)) == date(2026, 12, 24)
    assert next_business_day(date(2026, 12, 25)) == date(2026, 12, 29)


# ---- previous_business_day --------------------------------------------------


def test_previous_business_day_idempotent_on_business_day():  # CC-CAL-PREV-1
    d = date(2026, 6, 10)
    assert previous_business_day(d) == d


def test_previous_business_day_skips_weekend():  # CC-CAL-PREV-2
    monday = date(2026, 6, 15)
    assert previous_business_day(monday - timedelta(days=1)) == date(2026, 6, 12)


def test_previous_business_day_skips_bank_holiday():  # CC-CAL-PREV-3
    # 5 May 2026 (Tue) → prev BD from Mon 4th (holiday) = Fri 1st May
    assert previous_business_day(date(2026, 5, 4)) == date(2026, 5, 1)


# ---- business_days_between --------------------------------------------------


def test_business_days_between_same_day_is_zero():  # CC-CAL-BDB-1
    d = date(2026, 6, 10)
    assert business_days_between(d, d) == 0


def test_business_days_between_one_week():  # CC-CAL-BDB-2
    # Mon 8 Jun → Mon 15 Jun 2026: 5 business days (no bank holiday)
    assert business_days_between(date(2026, 6, 8), date(2026, 6, 15)) == 5


def test_business_days_between_over_bank_holiday():  # CC-CAL-BDB-3
    # 1 May (Fri) → 6 May (Wed) 2026: Fri + Mon(holiday skipped) + Tue = 2 BDs
    # [May 1 Fri=1, May 2 Sat=0, May 3 Sun=0, May 4 Mon(holiday)=0, May 5 Tue=1]
    # = 2 business days in [May 1, May 6)
    assert business_days_between(date(2026, 5, 1), date(2026, 5, 6)) == 2


def test_business_days_between_reversed_is_negative():  # CC-CAL-BDB-4
    a, b = date(2026, 6, 8), date(2026, 6, 15)
    assert business_days_between(b, a) == -business_days_between(a, b)


# ---- horizon tripwire -------------------------------------------------------


def test_is_bank_holiday_raises_beyond_horizon():  # CC-CAL-HOR-1
    beyond = DATA_HORIZON + timedelta(days=1)
    with pytest.raises(BankHolidayHorizonError):
        is_bank_holiday(beyond)


def test_is_business_day_raises_beyond_horizon():  # CC-CAL-HOR-2
    with pytest.raises(BankHolidayHorizonError):
        is_business_day(DATA_HORIZON + timedelta(days=1))


def test_next_business_day_raises_beyond_horizon():  # CC-CAL-HOR-3
    with pytest.raises(BankHolidayHorizonError):
        next_business_day(DATA_HORIZON + timedelta(days=1))


def test_horizon_error_message_mentions_horizon():  # CC-CAL-HOR-4
    with pytest.raises(BankHolidayHorizonError, match=str(DATA_HORIZON)):
        is_bank_holiday(DATA_HORIZON + timedelta(days=1))


def test_data_horizon_is_dec_31():  # CC-CAL-HOR-5
    assert DATA_HORIZON.month == 12 and DATA_HORIZON.day == 31


# ---- horizon_needs_refresh --------------------------------------------------


def test_horizon_needs_refresh_far_future():  # CC-CAL-REFR-1
    # 3 years before horizon → no refresh needed
    far = DATA_HORIZON - timedelta(days=3 * 365)
    assert not horizon_needs_refresh(far)


def test_horizon_needs_refresh_within_lead():  # CC-CAL-REFR-2
    # 1 day before default 180-day lead → needs refresh
    near = DATA_HORIZON - timedelta(days=179)
    assert horizon_needs_refresh(near)


def test_horizon_needs_refresh_custom_lead():  # CC-CAL-REFR-3
    target = DATA_HORIZON - timedelta(days=30)
    assert not horizon_needs_refresh(target, lead=timedelta(days=29))
    assert horizon_needs_refresh(target, lead=timedelta(days=31))


def test_horizon_needs_refresh_on_horizon():  # CC-CAL-REFR-4
    assert horizon_needs_refresh(DATA_HORIZON)


# ---- CI freshness tripwire (12-month rule) ----------------------------------


def test_data_horizon_at_least_12_months_ahead():  # CC-CAL-FRESH-1
    """Fails when DATA_HORIZON is within 12 months of today.

    This is the annual refresh reminder: when CI starts failing here, add the
    next year's bank-holiday data and bump DATA_HORIZON.
    """
    today = date.today()
    months_remaining = (DATA_HORIZON.year - today.year) * 12 + (DATA_HORIZON.month - today.month)
    assert months_remaining >= 12, (
        f"DATA_HORIZON ({DATA_HORIZON}) is less than 12 months ahead of today ({today}). "
        "Add next year's bank-holiday data to clonway_cockpit.uk_calendar and bump DATA_HORIZON."
    )
