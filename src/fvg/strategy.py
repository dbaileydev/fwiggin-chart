from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .detector import (
    FVGSide,
    FairValueGap,
    detect_fvgs,
    displacement_valid,
    entry_price_for_gap,
)


@dataclass
class StrategyConfig:
    entry_mode: str = "ce"
    require_trend: bool = True
    trend_ema_period: int = 50
    trade_bullish: bool = True
    trade_bearish: bool = True
    one_trade_at_a_time: bool = True
    stop_buffer_ticks: int = 2
    risk_reward: float = 2.0
    min_gap_points: float = 2.0
    max_age_bars: int = 48
    tick_size: float = 0.25
    session_enabled: bool = False
    session_start: str = "09:30"
    session_end: str = "16:00"
    session_timezone: str = "America/New_York"
    min_stop_points: float = 20.0
    require_trend_at_entry: bool = True
    displacement_enabled: bool = True
    displacement_atr_period: int = 14
    displacement_min_body_ratio: float = 0.5
    displacement_min_atr_multiple: float = 1.0
    require_rejection: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "StrategyConfig":
        session = raw.get("session", {})
        fvg = raw.get("fvg", {})
        disp = raw.get("displacement", {})
        return cls(
            entry_mode=raw.get("entry_mode", "ce"),
            require_trend=raw.get("require_trend", True),
            trend_ema_period=raw.get("trend_ema_period", 50),
            trade_bullish=raw.get("trade_bullish", True),
            trade_bearish=raw.get("trade_bearish", True),
            one_trade_at_a_time=raw.get("one_trade_at_a_time", True),
            stop_buffer_ticks=raw.get("stop_buffer_ticks", 2),
            risk_reward=raw.get("risk_reward", 2.0),
            min_gap_points=fvg.get("min_gap_points", 2.0),
            max_age_bars=fvg.get("max_age_bars", 48),
            tick_size=raw.get("tick_size", 0.25),
            session_enabled=session.get("enabled", False),
            session_start=session.get("start", "09:30"),
            session_end=session.get("end", "16:00"),
            session_timezone=session.get("timezone", "America/New_York"),
            min_stop_points=raw.get("min_stop_points", 20.0),
            require_trend_at_entry=raw.get("require_trend_at_entry", True),
            displacement_enabled=disp.get("enabled", True),
            displacement_atr_period=disp.get("atr_period", 14),
            displacement_min_body_ratio=disp.get("min_body_ratio", 0.5),
            displacement_min_atr_multiple=disp.get("min_atr_multiple", 1.0),
            require_rejection=raw.get("require_rejection", False),
        )


@dataclass
class PendingSetup:
    gap: FairValueGap
    entry_price: float
    stop_price: float
    target_price: float
    side: FVGSide


def _in_session(ts: pd.Timestamp, cfg: StrategyConfig) -> bool:
    if not cfg.session_enabled:
        return True
    local = ts.tz_localize("UTC").tz_convert(cfg.session_timezone)
    start_h, start_m = map(int, cfg.session_start.split(":"))
    end_h, end_m = map(int, cfg.session_end.split(":"))
    minutes = local.hour * 60 + local.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    return start_minutes <= minutes <= end_minutes


def _trend_allows(side: FVGSide, close: float, ema: float, require_trend: bool) -> bool:
    if not require_trend:
        return True
    if side == FVGSide.BULLISH:
        return close >= ema
    return close <= ema


def build_pending_setups(
    df: pd.DataFrame,
    cfg: StrategyConfig,
    gaps: list[FairValueGap] | None = None,
    *,
    ema_series: pd.Series | None = None,
    displacement_bars: set[int] | None = None,
) -> list[PendingSetup]:
    if gaps is None:
        gaps = detect_fvgs(df, min_gap_points=cfg.min_gap_points)

    ema = ema_series if ema_series is not None else df["close"].ewm(span=cfg.trend_ema_period, adjust=False).mean()
    buffer = cfg.stop_buffer_ticks * cfg.tick_size
    setups: list[PendingSetup] = []

    for gap in gaps:
        bar_idx = gap.formed_bar
        if bar_idx >= len(df):
            continue

        close = float(df["close"].iloc[bar_idx])
        ema_val = float(ema.iloc[bar_idx])
        ts = pd.Timestamp(df.index[bar_idx])

        if not _in_session(ts, cfg):
            continue
        if gap.side == FVGSide.BULLISH and not cfg.trade_bullish:
            continue
        if gap.side == FVGSide.BEARISH and not cfg.trade_bearish:
            continue
        if not _trend_allows(gap.side, close, ema_val, cfg.require_trend):
            continue
        if cfg.displacement_enabled:
            if displacement_bars is not None:
                if gap.formed_bar not in displacement_bars:
                    continue
            elif not displacement_valid(
                df,
                gap.formed_bar,
                atr_period=cfg.displacement_atr_period,
                min_body_ratio=cfg.displacement_min_body_ratio,
                min_atr_multiple=cfg.displacement_min_atr_multiple,
            ):
                continue

        entry = entry_price_for_gap(gap, cfg.entry_mode)
        if gap.side == FVGSide.BULLISH:
            stop = gap.bottom - buffer
            risk = entry - stop
            if risk <= 0:
                continue
            target = entry + risk * cfg.risk_reward
        else:
            stop = gap.top + buffer
            risk = stop - entry
            if risk <= 0:
                continue
            target = entry - risk * cfg.risk_reward

        if risk < cfg.min_stop_points:
            continue

        setups.append(
            PendingSetup(
                gap=gap,
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                side=gap.side,
            )
        )

    return setups
