from __future__ import annotations

US_MARKET_HOLIDAYS = {
    20240101, 20240115, 20240219, 20240329, 20240527, 20240619, 20240704, 20240902, 20241128, 20241225,
    20250101, 20250120, 20250217, 20250418, 20250526, 20250619, 20250704, 20250901, 20251127, 20251225,
    20260101, 20260119, 20260216, 20260403, 20260525, 20260619, 20260703, 20260907, 20261126, 20261225,
    20270101, 20270118, 20270215, 20270326, 20270531, 20270618, 20270705, 20270906, 20271125, 20271224,
}

FOMC_DATES = {
    20240131, 20240320, 20240501, 20240612, 20240731, 20240918, 20241107, 20241218,
    20250129, 20250319, 20250507, 20250618, 20250730, 20250917, 20251029, 20251210,
    20260128, 20260318, 20260429, 20260617, 20260729, 20260916, 20261028, 20261209,
    20270127, 20270317, 20270428, 20270609, 20270728, 20270915, 20271027, 20271208,
}


def date_key(ts) -> int:
    return ts.year * 10000 + ts.month * 100 + ts.day


def is_us_holiday(ts, *, skip: bool = True) -> bool:
    return skip and date_key(ts) in US_MARKET_HOLIDAYS


def is_fomc_day(ts, *, skip: bool = True) -> bool:
    return skip and date_key(ts) in FOMC_DATES


def is_trading_day(ts, *, skip_holidays: bool = True, skip_fomc: bool = True) -> bool:
    if ts.weekday() >= 5:
        return False
    if is_us_holiday(ts, skip=skip_holidays):
        return False
    if is_fomc_day(ts, skip=skip_fomc):
        return False
    return True
