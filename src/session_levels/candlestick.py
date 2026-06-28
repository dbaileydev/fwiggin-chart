"""Candlestick alignment checks for VWAP cross entries (mirrors Pine logic)."""

from __future__ import annotations

import numpy as np

from .config import SessionLevelsConfig


def _metrics(o: float, h: float, l: float, c: float) -> dict[str, float | bool]:
    candle_range = h - l
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    body_pct = body / candle_range if candle_range > 0 else 0.0
    clv = (c - l) / candle_range if candle_range > 0 else 0.5
    return {
        "range": candle_range,
        "body": body,
        "upper_wick": upper_wick,
        "lower_wick": lower_wick,
        "body_pct": body_pct,
        "clv": clv,
        "bullish": c > o,
        "bearish": c < o,
    }


def _min_range(cfg: SessionLevelsConfig) -> float:
    return cfg.tick_size * 8


def align_long(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    i: int,
    cfg: SessionLevelsConfig,
) -> bool:
    if not cfg.use_candle_confirm:
        return True
    if i < 1:
        return False

    cur = _metrics(float(o[i]), float(h[i]), float(l[i]), float(c[i]))
    prev = _metrics(float(o[i - 1]), float(h[i - 1]), float(l[i - 1]), float(c[i - 1]))
    if cur["range"] < _min_range(cfg):
        return False

    pin = cfg.candle_pin_wick_ratio
    clv_hi = cfg.candle_clv_threshold

    shooting_star = (
        cur["upper_wick"] >= cur["body"] * pin
        and cur["upper_wick"] > cur["lower_wick"] * 1.5
    )
    hammer = (
        cur["lower_wick"] >= cur["body"] * pin
        and cur["lower_wick"] > cur["upper_wick"] * 1.5
    )
    doji = cur["body_pct"] <= 0.10
    bull_engulf = (
        prev["bearish"]
        and cur["bullish"]
        and c[i] > o[i - 1]
        and o[i] <= c[i - 1]
    )
    bear_engulf = (
        prev["bullish"]
        and cur["bearish"]
        and c[i] < o[i - 1]
        and o[i] >= c[i - 1]
    )
    bull_marobozu = (
        cur["bullish"]
        and cur["body_pct"] >= cfg.candle_min_body_pct
        and cur["upper_wick"] <= cur["body"] * 0.25
        and cur["lower_wick"] <= cur["body"] * 0.25
    )

    if not cur["bullish"] or shooting_star or bear_engulf or doji:
        return False

    return bool(
        hammer
        or bull_engulf
        or bull_marobozu
        or cur["clv"] >= clv_hi
    )


def align_short(
    o: np.ndarray,
    h: np.ndarray,
    l: np.ndarray,
    c: np.ndarray,
    i: int,
    cfg: SessionLevelsConfig,
) -> bool:
    if not cfg.use_candle_confirm:
        return True
    if i < 1:
        return False

    cur = _metrics(float(o[i]), float(h[i]), float(l[i]), float(c[i]))
    prev = _metrics(float(o[i - 1]), float(h[i - 1]), float(l[i - 1]), float(c[i - 1]))
    if cur["range"] < _min_range(cfg):
        return False

    pin = cfg.candle_pin_wick_ratio
    clv_lo = 1.0 - cfg.candle_clv_threshold

    shooting_star = (
        cur["upper_wick"] >= cur["body"] * pin
        and cur["upper_wick"] > cur["lower_wick"] * 1.5
    )
    hammer = (
        cur["lower_wick"] >= cur["body"] * pin
        and cur["lower_wick"] > cur["upper_wick"] * 1.5
    )
    doji = cur["body_pct"] <= 0.10
    bull_engulf = (
        prev["bearish"]
        and cur["bullish"]
        and c[i] > o[i - 1]
        and o[i] <= c[i - 1]
    )
    bear_engulf = (
        prev["bullish"]
        and cur["bearish"]
        and c[i] < o[i - 1]
        and o[i] >= c[i - 1]
    )
    bear_marobozu = (
        cur["bearish"]
        and cur["body_pct"] >= cfg.candle_min_body_pct
        and cur["upper_wick"] <= cur["body"] * 0.25
        and cur["lower_wick"] <= cur["body"] * 0.25
    )

    if not cur["bearish"] or hammer or bull_engulf or doji:
        return False

    return bool(
        shooting_star
        or bear_engulf
        or bear_marobozu
        or cur["clv"] <= clv_lo
    )
