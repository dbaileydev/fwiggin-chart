from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd

DateRangeKey = Literal[
    "7d", "30d", "90d", "this_year", "last_year", "all_time"
]


@dataclass(frozen=True)
class ResolvedRange:
    key: DateRangeKey
    label: str
    start: datetime | None
    end: datetime
    interval: str
    yfinance_period: str | None


def _now_et() -> datetime:
    return pd.Timestamp.now(tz="America/New_York").to_pydatetime()


def resolve_range(key: DateRangeKey, *, now: datetime | None = None) -> ResolvedRange:
    now = now or _now_et()
    labels = {
        "7d": "Last 7 days",
        "30d": "Last 30 days",
        "90d": "Last 90 days",
        "this_year": "This year",
        "last_year": "Last year",
        "all_time": "All time",
    }

    if key == "7d":
        return ResolvedRange(
            key=key,
            label=labels[key],
            start=now - timedelta(days=7),
            end=now,
            interval="5m",
            yfinance_period="7d",
        )
    if key == "30d":
        return ResolvedRange(
            key=key,
            label=labels[key],
            start=now - timedelta(days=30),
            end=now,
            interval="5m",
            yfinance_period="60d",
        )
    if key == "90d":
        return ResolvedRange(
            key=key,
            label=labels[key],
            start=now - timedelta(days=90),
            end=now,
            interval="1h",
            yfinance_period="90d",
        )
    if key == "this_year":
        return ResolvedRange(
            key=key,
            label=labels[key],
            start=datetime(now.year, 1, 1),
            end=now,
            interval="1h",
            yfinance_period="ytd",
        )
    if key == "last_year":
        return ResolvedRange(
            key=key,
            label=labels[key],
            start=datetime(now.year - 1, 1, 1),
            end=datetime(now.year - 1, 12, 31, 23, 59, 59),
            interval="1d",
            yfinance_period="730d",
        )
    return ResolvedRange(
        key=key,
        label=labels[key],
        start=None,
        end=now,
        interval="1d",
        yfinance_period="max",
    )
