from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class FVGSide(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


@dataclass(frozen=True)
class FairValueGap:
    side: FVGSide
    top: float
    bottom: float
    formed_bar: int
    formed_at: pd.Timestamp

    @property
    def midpoint(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def size(self) -> float:
        return self.top - self.bottom


def detect_fvgs(
    df: pd.DataFrame,
    *,
    min_gap_points: float = 0.0,
) -> list[FairValueGap]:
    """Detect 3-candle fair value gaps on OHLC data.

    Bullish FVG: middle candle displaces up; low[i] > high[i-2].
    Bearish FVG: middle candle displaces down; high[i] < low[i-2].
    """
    if len(df) < 3:
        return []

    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    timestamps = df.index.to_numpy()

    gaps: list[FairValueGap] = []

    for i in range(2, len(df)):
        # Bullish imbalance
        if lows[i] > highs[i - 2]:
            top = lows[i]
            bottom = highs[i - 2]
            size = top - bottom
            if size >= min_gap_points:
                gaps.append(
                    FairValueGap(
                        side=FVGSide.BULLISH,
                        top=top,
                        bottom=bottom,
                        formed_bar=i,
                        formed_at=pd.Timestamp(timestamps[i]),
                    )
                )

        # Bearish imbalance
        if highs[i] < lows[i - 2]:
            top = lows[i - 2]
            bottom = highs[i]
            size = top - bottom
            if size >= min_gap_points:
                gaps.append(
                    FairValueGap(
                        side=FVGSide.BEARISH,
                        top=top,
                        bottom=bottom,
                        formed_bar=i,
                        formed_at=pd.Timestamp(timestamps[i]),
                    )
                )

    return gaps


def is_fvg_invalidated(
    gap: FairValueGap,
    bar_high: float,
    bar_low: float,
    *,
    use_close: bool = False,
    bar_close: float | None = None,
) -> bool:
    """Return True when price fully violates the gap."""
    if gap.side == FVGSide.BULLISH:
        if use_close and bar_close is not None:
            return bar_close < gap.bottom
        return bar_low < gap.bottom

    if use_close and bar_close is not None:
        return bar_close > gap.top
    return bar_high > gap.top


def price_touches_gap(gap: FairValueGap, bar_high: float, bar_low: float) -> bool:
    return bar_low <= gap.top and bar_high >= gap.bottom


def displacement_valid(
    df: pd.DataFrame,
    formed_bar: int,
    *,
    atr_period: int = 14,
    min_body_ratio: float = 0.5,
    min_atr_multiple: float = 1.0,
) -> bool:
    """Middle candle of the 3-bar FVG must be a strong impulse."""
    mid = formed_bar - 1
    if mid < 0 or formed_bar >= len(df):
        return False

    o = float(df["open"].iloc[mid])
    h = float(df["high"].iloc[mid])
    l = float(df["low"].iloc[mid])
    c = float(df["close"].iloc[mid])

    candle_range = h - l
    if candle_range <= 0:
        return False

    body = abs(c - o)
    if body / candle_range < min_body_ratio:
        return False

    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(atr_period, min_periods=atr_period).mean()
    atr_val = float(atr.iloc[mid])
    if np.isnan(atr_val) or candle_range < atr_val * min_atr_multiple:
        return False

    return True


def entry_price_for_gap(gap: FairValueGap, mode: str) -> float:
    mode = mode.lower()
    if mode == "ce":
        return gap.midpoint
    if mode == "edge":
        return gap.top if gap.side == FVGSide.BULLISH else gap.bottom
    if mode == "full":
        return gap.bottom if gap.side == FVGSide.BULLISH else gap.top
    raise ValueError(f"Unknown entry mode: {mode}")
