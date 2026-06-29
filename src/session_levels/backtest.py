from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum

import numpy as np
import pandas as pd

from .calendar import is_trading_day
from .candlestick import align_long, align_short
from .config import SessionLevelsConfig


class ExitReason(str, Enum):
    STOP = "stop"
    TARGET = "target"
    PARTIAL = "partial"
    TRAIL = "trail"
    FLATTEN_2PM = "2pm_flatten"
    SESSION_END = "session_end"
    END = "end_of_data"


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    contracts: int
    pnl_net: float
    exit_reason: ExitReason


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    config: SessionLevelsConfig
    summary: dict[str, float | int]


def _mins_et(ts: pd.Timestamp) -> int:
    ts = ts.tz_convert("America/New_York")
    return ts.hour * 60 + ts.minute


def _mins_ct(ts: pd.Timestamp) -> int:
    ts = ts.tz_convert("America/Chicago")
    return ts.hour * 60 + ts.minute


def _in_rth(ts: pd.Timestamp) -> bool:
    ts = ts.tz_convert("America/New_York")
    if ts.weekday() >= 5:
        return False
    t = ts.time()
    return time(9, 30) <= t < time(16, 0)


def _precompute(df: pd.DataFrame, cfg: SessionLevelsConfig) -> dict[str, np.ndarray]:
    n = len(df)
    idx = df.index
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    v = np.maximum(df["volume"].to_numpy(float), 1.0)
    hlc3 = (h + l + c) / 3.0

    in_rth = np.zeros(n, dtype=bool)
    trading_day = np.zeros(n, dtype=bool)
    for i, ts in enumerate(idx):
        in_rth[i] = _in_rth(ts)
        trading_day[i] = is_trading_day(
            ts.tz_convert("America/New_York"),
            skip_holidays=cfg.skip_us_holidays,
            skip_fomc=cfg.skip_fomc_days,
        )

    session_vwap = np.full(n, np.nan)
    prior_day_vwap = np.full(n, np.nan)
    or_ready = np.zeros(n, dtype=bool)
    or_after_period = np.zeros(n, dtype=bool)

    sess_pv = 0.0
    sess_v = 0.0
    prior_pv = 0.0
    prior_v = 0.0
    prior_session_start = -1
    last_prior_anchor = -1

    or_high = np.nan
    or_low = np.nan
    or_start_i = -1
    or_start_ts = None
    or_done = False
    or_ms = cfg.or_minutes * 60 * 1000

    prev_in_rth = False
    session_start_i = -1

    for i, ts in enumerate(idx):
        ir = in_rth[i] and trading_day[i]
        rth_started = ir and not prev_in_rth
        rth_ended = prev_in_rth and not ir

        if rth_started:
            sess_pv = hlc3[i] * v[i]
            sess_v = v[i]
            or_high = h[i]
            or_low = l[i]
            or_start_i = i
            or_start_ts = ts
            or_done = False
            session_start_i = i
        elif ir:
            sess_pv += hlc3[i] * v[i]
            sess_v += v[i]
            if not or_done and or_start_i >= 0 and or_start_ts is not None:
                elapsed_ms = (ts - or_start_ts).total_seconds() * 1000
                if elapsed_ms < or_ms:
                    or_high = max(or_high, h[i])
                    or_low = min(or_low, l[i])
                elif not np.isnan(or_high) and not np.isnan(or_low):
                    or_done = True
                    or_ready[i] = True
                if elapsed_ms > or_ms:
                    or_after_period[i] = True

        if ir and or_done:
            or_ready[i] = True
        if ir and or_start_ts is not None and (ts - or_start_ts).total_seconds() * 1000 > or_ms:
            or_after_period[i] = True

        if ir and sess_v > 0:
            session_vwap[i] = sess_pv / sess_v

        if rth_ended and trading_day[i - 1 if i > 0 else i]:
            prior_session_start = session_start_i

        if prior_session_start >= 0 and ir:
            if prior_session_start != last_prior_anchor:
                last_prior_anchor = prior_session_start
                prior_pv = 0.0
                prior_v = 0.0
                for j in range(prior_session_start, i + 1):
                    if in_rth[j] and trading_day[j]:
                        prior_pv += hlc3[j] * v[j]
                        prior_v += v[j]
            else:
                prior_pv += hlc3[i] * v[i]
                prior_v += v[i]
            if prior_v > 0:
                prior_day_vwap[i] = prior_pv / prior_v

        prev_in_rth = ir

    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "in_rth": in_rth,
        "trading_day": trading_day,
        "session_vwap": session_vwap,
        "prior_day_vwap": prior_day_vwap,
        "or_ready": or_ready,
        "or_after_period": or_after_period,
    }


@dataclass
class _Position:
    side: str
    qty: int
    entry_px: float
    entry_time: pd.Timestamp
    entry_bar: int
    stop_px: float
    tp_px: float
    partial_px: float
    risk: float
    partial_taken: bool = False
    trailing: bool = False
    trail_stop: float | None = None


@dataclass
class _SessionState:
    traded_today: bool = False
    last_loss_exit_bar: int | None = None
    last_long_exit_bar: int | None = None
    last_short_exit_bar: int | None = None
    flattened_at_2pm: bool = False
    session_start_equity: float = 0.0
    session_start_bar: int = -1
    long_win_watch: bool = False
    short_win_watch: bool = False
    skip_next_long: bool = False
    skip_next_short: bool = False
    position_start_equity: float | None = None
    loss_streak_paused: bool = False
    trading_paused: bool = False
    consecutive_loss_days: int = 0
    consecutive_recovery_wins: int = 0
    paper_traded_today: bool = False
    paper_active: bool = False
    paper_stopped: bool = False
    paper_entry_px: float = 0.0
    paper_stop_px: float = 0.0
    paper_dir: int = 0


def _pnl(side: str, entry: float, exit_px: float, contracts: int, cfg: SessionLevelsConfig) -> float:
    direction = 1 if side == "long" else -1
    points = (exit_px - entry) * direction
    return points * cfg.point_value * contracts


def run_backtest(df: pd.DataFrame, cfg: SessionLevelsConfig | None = None) -> BacktestResult:
    cfg = cfg or SessionLevelsConfig()
    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("America/New_York")
    else:
        df = df.copy()
        df.index = df.index.tz_convert("America/New_York")

    data = _precompute(df, cfg)
    n = len(df)
    idx = df.index
    o, h, l, c = data["open"], data["high"], data["low"], data["close"]
    in_rth = data["in_rth"]
    trading_day = data["trading_day"]
    session_vwap = data["session_vwap"]
    prior_day_vwap = data["prior_day_vwap"]
    or_ready = data["or_ready"]
    or_after_period = data["or_after_period"]

    stop_buf = cfg.stop_buffer_ticks * cfg.tick_size
    entry_cutoff_mins_ct = cfg.entry_end_hour_ct * 60 + cfg.entry_end_minute_ct
    entry_start_mins_et = cfg.entry_start_hour_et * 60 + cfg.entry_start_minute_et
    partial_qty = int(np.floor(cfg.trade_qty * cfg.partial_exit_pct / 100.0))

    equity = cfg.initial_capital
    equity_points: list[tuple[pd.Timestamp, float]] = []
    trades: list[Trade] = []
    pos: _Position | None = None
    sess = _SessionState()
    prev_in_rth = False

    def close_leg(
        side: str,
        entry_px: float,
        entry_time: pd.Timestamp,
        exit_px: float,
        exit_time: pd.Timestamp,
        contracts: int,
        reason: ExitReason,
        bar_i: int,
    ) -> float:
        nonlocal equity
        net = _pnl(side, entry_px, exit_px, contracts, cfg)
        equity += net
        if net < 0 and sess.session_start_bar >= 0 and bar_i >= sess.session_start_bar:
            sess.last_loss_exit_bar = bar_i
        trades.append(
            Trade(
                side=side,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_px,
                exit_price=exit_px,
                contracts=contracts,
                pnl_net=net,
                exit_reason=reason,
            )
        )
        return net

    for i in range(n):
        ts = idx[i]
        ir = bool(in_rth[i] and trading_day[i])
        rth_started = ir and not prev_in_rth
        rth_ended = prev_in_rth and not ir

        if rth_started:
            sess = _SessionState(
                loss_streak_paused=sess.loss_streak_paused,
                consecutive_loss_days=sess.consecutive_loss_days,
                consecutive_recovery_wins=sess.consecutive_recovery_wins,
            )
            sess.session_start_equity = equity
            sess.session_start_bar = i
            sess.trading_paused = cfg.use_loss_streak_pause and sess.loss_streak_paused

        sv = session_vwap[i]
        pv = prior_day_vwap[i]
        prev_sv = session_vwap[i - 1] if i > 0 else np.nan
        prev_pv = prior_day_vwap[i - 1] if i > 0 else np.nan
        prev_c = c[i - 1] if i > 0 else c[i]

        # Session end flatten on first bar after RTH (matches Pine rthEnded block)
        if rth_ended and pos is not None:
            side = pos.side
            close_leg(
                side, pos.entry_px, pos.entry_time, c[i], ts, pos.qty,
                ExitReason.SESSION_END, i,
            )
            if side == "long":
                sess.last_long_exit_bar = i
            else:
                sess.last_short_exit_bar = i
            if sess.position_start_equity is not None and equity > sess.position_start_equity:
                if side == "long":
                    sess.long_win_watch = True
                else:
                    sess.short_win_watch = True
            sess.position_start_equity = None
            pos = None

        # ── Manage open position (exits on bars after entry) ──
        if pos is not None and i > pos.entry_bar:
            side = pos.side
            exited = False

            if pos is not None and cfg.flatten_at_2pm and ir and not sess.flattened_at_2pm:
                if _mins_ct(ts) >= entry_cutoff_mins_ct:
                    close_leg(
                        side, pos.entry_px, pos.entry_time, c[i], ts, pos.qty,
                        ExitReason.FLATTEN_2PM, i,
                    )
                    pos = None
                    sess.flattened_at_2pm = True
                    if side == "long":
                        sess.last_long_exit_bar = i
                    else:
                        sess.last_short_exit_bar = i
                    exited = True

            if pos is not None and not exited:
                side = pos.side

                # Update swing trail level when already trailing
                if pos.trailing:
                    if side == "long":
                        swing = min(l[i - k] for k in range(min(int(cfg.trail_lookback), i + 1)))
                        new_trail = swing - stop_buf
                        if pos.trail_stop is None or new_trail > pos.trail_stop:
                            pos.trail_stop = new_trail
                    else:
                        swing = max(h[i - k] for k in range(min(int(cfg.trail_lookback), i + 1)))
                        new_trail = swing + stop_buf
                        if pos.trail_stop is None or new_trail < pos.trail_stop:
                            pos.trail_stop = new_trail

                active_stop = pos.trail_stop if pos.trailing and pos.trail_stop is not None else pos.stop_px

                # 1) Stop / trail — exit full remaining size intrabar
                stop_hit = (side == "long" and l[i] <= active_stop) or (side == "short" and h[i] >= active_stop)
                if stop_hit:
                    reason = ExitReason.TRAIL if pos.trailing else ExitReason.STOP
                    close_leg(
                        side, pos.entry_px, pos.entry_time, active_stop, ts, pos.qty,
                        reason, i,
                    )
                    if side == "long":
                        sess.last_long_exit_bar = i
                    else:
                        sess.last_short_exit_bar = i
                    pos = None
                    exited = True

                # 2) Partial at 2R (before trail activates on this bar)
                elif (
                    not pos.partial_taken
                    and partial_qty >= 1
                    and partial_qty < cfg.trade_qty
                ):
                    if side == "long" and h[i] >= pos.partial_px and l[i] > pos.stop_px:
                        close_leg(
                            side, pos.entry_px, pos.entry_time, pos.partial_px, ts,
                            partial_qty, ExitReason.PARTIAL, i,
                        )
                        pos.qty -= partial_qty
                        pos.partial_taken = True
                    elif side == "short" and l[i] <= pos.partial_px and h[i] < pos.stop_px:
                        close_leg(
                            side, pos.entry_px, pos.entry_time, pos.partial_px, ts,
                            partial_qty, ExitReason.PARTIAL, i,
                        )
                        pos.qty -= partial_qty
                        pos.partial_taken = True

                # 3) Activate trail on runner at trail R:R
                if pos is not None and not pos.trailing:
                    if side == "long" and h[i] >= pos.entry_px + pos.risk * cfg.trail_activate_rr:
                        pos.trailing = True
                        swing = min(l[i - k] for k in range(min(int(cfg.trail_lookback), i + 1)))
                        pos.trail_stop = swing - stop_buf
                    elif side == "short" and l[i] <= pos.entry_px - pos.risk * cfg.trail_activate_rr:
                        pos.trailing = True
                        swing = max(h[i - k] for k in range(min(int(cfg.trail_lookback), i + 1)))
                        pos.trail_stop = swing + stop_buf

                # 4) Hard TP at 3R while pre-trail
                if pos is not None and not exited and not pos.trailing:
                    tp_hit = (side == "long" and h[i] >= pos.tp_px) or (side == "short" and l[i] <= pos.tp_px)
                    if tp_hit:
                        close_leg(
                            side, pos.entry_px, pos.entry_time, pos.tp_px, ts, pos.qty,
                            ExitReason.TARGET, i,
                        )
                        if side == "long":
                            sess.last_long_exit_bar = i
                        else:
                            sess.last_short_exit_bar = i
                        pos = None

        # Win-watch after directional exit
        if pos is None and sess.last_long_exit_bar == i and sess.position_start_equity is not None:
            if equity > sess.position_start_equity:
                sess.long_win_watch = True
                sess.skip_next_long = False
            sess.position_start_equity = None
        if pos is None and sess.last_short_exit_bar == i and sess.position_start_equity is not None:
            if equity > sess.position_start_equity:
                sess.short_win_watch = True
                sess.skip_next_short = False
            sess.position_start_equity = None

        if cfg.use_skip_first_reclaim_after_win and pos is None and not np.isnan(sv):
            if sess.long_win_watch and c[i] < sv:
                sess.skip_next_long = True
                sess.long_win_watch = False
            if sess.short_win_watch and c[i] > sv:
                sess.skip_next_short = True
                sess.short_win_watch = False

        # Loss streak at session end
        if rth_ended and prev_in_rth and cfg.use_loss_streak_pause and i > 0:
            ended_pnl = equity - sess.session_start_equity
            if sess.trading_paused:
                if sess.paper_traded_today:
                    paper_win = (
                        not sess.paper_stopped
                        and (
                            (sess.paper_dir == 1 and c[i - 1] - sess.paper_entry_px > 0)
                            or (sess.paper_dir == -1 and sess.paper_entry_px - c[i - 1] > 0)
                        )
                    )
                    sess.consecutive_recovery_wins = (
                        sess.consecutive_recovery_wins + 1 if paper_win else 0
                    )
                    if sess.consecutive_recovery_wins >= cfg.recovery_win_days:
                        sess.loss_streak_paused = False
                        sess.consecutive_recovery_wins = 0
                        sess.consecutive_loss_days = 0
                else:
                    sess.consecutive_recovery_wins = 0
            elif sess.traded_today:
                if ended_pnl < 0:
                    sess.consecutive_loss_days += 1
                else:
                    sess.consecutive_loss_days = 0
                if sess.consecutive_loss_days >= cfg.loss_streak_days:
                    sess.loss_streak_paused = True
                    sess.consecutive_recovery_wins = 0
            else:
                sess.consecutive_loss_days = 0

        # ── Entry signals (process_orders_on_close → entry at bar close) ──
        before_cutoff = _mins_ct(ts) < entry_cutoff_mins_ct
        after_start = _mins_et(ts) >= entry_start_mins_et
        after_or = or_after_period[i]
        can_enter = (
            before_cutoff
            and after_start
            and (after_or if cfg.wait_for_or else ir)
        )

        above_both = not np.isnan(sv) and not np.isnan(pv) and c[i] > sv and c[i] > pv
        below_both = not np.isnan(sv) and not np.isnan(pv) and c[i] < sv and c[i] < pv

        cross_above_sess = (
            not np.isnan(sv) and not np.isnan(prev_sv)
            and c[i] > sv and prev_c <= prev_sv
        )
        cross_above_pd = (
            not np.isnan(pv) and not np.isnan(prev_pv)
            and c[i] > pv and prev_c <= prev_pv
        )
        cross_below_sess = (
            not np.isnan(sv) and not np.isnan(prev_sv)
            and c[i] < sv and prev_c >= prev_sv
        )
        cross_below_pd = (
            not np.isnan(pv) and not np.isnan(prev_pv)
            and c[i] < pv and prev_c >= prev_pv
        )

        prior_range = h[i - 1] - l[i - 1] if i > 0 else 0.0
        prior_body_pct = abs(c[i - 1] - o[i - 1]) / prior_range if i > 0 and prior_range > 0 else 0.0
        strong_bear = cfg.opp_body_pct > 0 and i > 0 and c[i - 1] < o[i - 1] and prior_body_pct >= cfg.opp_body_pct
        strong_bull = (
            cfg.opp_body_pct_short > 0 and i > 0 and c[i - 1] > o[i - 1]
            and prior_body_pct >= cfg.opp_body_pct_short
        )

        long_risk = c[i] - (l[i] - stop_buf)
        short_risk = (h[i] + stop_buf) - c[i]

        within_dist_long = cfg.max_vwap_dist_pts <= 0 or (not np.isnan(sv) and c[i] - sv <= cfg.max_vwap_dist_pts)
        within_dist_short = cfg.max_vwap_dist_pts <= 0 or (not np.isnan(sv) and sv - c[i] <= cfg.max_vwap_dist_pts)
        valid_long_risk = cfg.max_entry_risk_pts <= 0 or long_risk <= cfg.max_entry_risk_pts
        valid_short_risk = cfg.max_entry_risk_pts <= 0 or short_risk <= cfg.max_entry_risk_pts

        spread_now = abs(sv - pv) if not np.isnan(sv) and not np.isnan(pv) else np.nan
        spread_ok = (
            cfg.min_vwap_spread_pts <= 0
            or (not np.isnan(spread_now) and spread_now >= cfg.min_vwap_spread_pts)
        )

        bars_since_sess = i - sess.session_start_bar if sess.session_start_bar >= 0 else 0
        can_flat = (
            bars_since_sess >= cfg.vwap_slope_lookback
            and not np.isnan(sv) and not np.isnan(pv)
            and i >= cfg.vwap_slope_lookback
            and not np.isnan(session_vwap[i - cfg.vwap_slope_lookback])
            and not np.isnan(prior_day_vwap[i - cfg.vwap_slope_lookback])
        )
        if can_flat:
            sess_slope = abs(sv - session_vwap[i - cfg.vwap_slope_lookback])
            pd_slope = abs(pv - prior_day_vwap[i - cfg.vwap_slope_lookback])
            compressed = cfg.max_vwap_spread_pts > 0 and not np.isnan(spread_now) and spread_now <= cfg.max_vwap_spread_pts
            sloping = (
                cfg.max_vwap_slope_pts > 0
                and sess_slope <= cfg.max_vwap_slope_pts
                and pd_slope <= cfg.max_vwap_slope_pts
            )
            both_flat = cfg.skip_flat_vwaps and compressed and sloping
        else:
            both_flat = False

        long_setup = can_enter and above_both and (cross_above_sess or cross_above_pd) and not strong_bear
        short_setup = can_enter and below_both and (cross_below_sess or cross_below_pd) and not strong_bull

        long_core = (
            long_setup and within_dist_long and valid_long_risk
            and spread_ok and not both_flat and align_long(o, h, l, c, i, cfg)
        )
        short_core = (
            short_setup and within_dist_short and valid_short_risk
            and spread_ok and not both_flat and align_short(o, h, l, c, i, cfg)
        )

        reclaim_block_long = cfg.use_skip_first_reclaim_after_win and sess.skip_next_long and long_core
        reclaim_block_short = cfg.use_skip_first_reclaim_after_win and sess.skip_next_short and short_core
        if reclaim_block_long:
            sess.skip_next_long = False
        if reclaim_block_short:
            sess.skip_next_short = False

        long_signal = long_core and not reclaim_block_long
        short_signal = short_core and not reclaim_block_short

        # Cooldowns
        in_loss_cd = (
            sess.last_loss_exit_bar is not None
            and sess.session_start_bar >= 0
            and sess.last_loss_exit_bar >= sess.session_start_bar
            and i - sess.last_loss_exit_bar < cfg.loss_cooldown
        )
        in_long_cd = (
            cfg.same_dir_cooldown > 0
            and sess.last_long_exit_bar is not None
            and sess.session_start_bar >= 0
            and sess.last_long_exit_bar >= sess.session_start_bar
            and i - sess.last_long_exit_bar < cfg.same_dir_cooldown
        )
        in_short_cd = (
            cfg.same_dir_cooldown > 0
            and sess.last_short_exit_bar is not None
            and sess.session_start_bar >= 0
            and sess.last_short_exit_bar >= sess.session_start_bar
            and i - sess.last_short_exit_bar < cfg.same_dir_cooldown
        )

        can_trade_base = (
            ir
            and pos is None
            and (not cfg.one_trade_per_day or not sess.traded_today)
            and not sess.trading_paused
        )

        # Entries at close
        if can_trade_base and not in_loss_cd and not in_long_cd and long_signal and long_risk > 0:
            entry_px = c[i]
            stop_px = l[i] - stop_buf
            pos = _Position(
                side="long",
                qty=cfg.trade_qty,
                entry_px=entry_px,
                entry_time=ts,
                entry_bar=i,
                stop_px=stop_px,
                tp_px=entry_px + long_risk * cfg.rr_ratio,
                partial_px=entry_px + long_risk * cfg.partial_exit_rr,
                risk=long_risk,
            )
            sess.traded_today = True
            sess.position_start_equity = equity

        elif can_trade_base and not in_loss_cd and not in_short_cd and short_signal and short_risk > 0:
            entry_px = c[i]
            stop_px = h[i] + stop_buf
            pos = _Position(
                side="short",
                qty=cfg.trade_qty,
                entry_px=entry_px,
                entry_time=ts,
                entry_bar=i,
                stop_px=stop_px,
                tp_px=entry_px - short_risk * cfg.rr_ratio,
                partial_px=entry_px - short_risk * cfg.partial_exit_rr,
                risk=short_risk,
            )
            sess.traded_today = True
            sess.position_start_equity = equity

        # Paper while paused
        if (
            sess.trading_paused and ir and before_cutoff and not sess.paper_traded_today
            and pos is None
        ):
            if long_signal and long_risk > 0:
                sess.paper_traded_today = True
                sess.paper_active = True
                sess.paper_entry_px = c[i]
                sess.paper_stop_px = l[i] - stop_buf
                sess.paper_dir = 1
                sess.paper_stopped = False
            elif short_signal and short_risk > 0:
                sess.paper_traded_today = True
                sess.paper_active = True
                sess.paper_entry_px = c[i]
                sess.paper_stop_px = h[i] + stop_buf
                sess.paper_dir = -1
                sess.paper_stopped = False

        if sess.paper_active and not sess.paper_stopped:
            if sess.paper_dir == 1 and l[i] <= sess.paper_stop_px:
                sess.paper_stopped = True
                sess.paper_active = False
            elif sess.paper_dir == -1 and h[i] >= sess.paper_stop_px:
                sess.paper_stopped = True
                sess.paper_active = False

        equity_points.append((ts, equity))
        prev_in_rth = ir

    if pos is not None:
        last_ts = idx[-1]
        close_leg(pos.side, pos.entry_px, pos.entry_time, c[-1], last_ts, pos.qty, ExitReason.END, n - 1)

    equity_curve = pd.Series(
        [v for _, v in equity_points],
        index=pd.DatetimeIndex([t for t, _ in equity_points]),
        name="equity",
    )
    summary = _summarize(trades, equity_curve, cfg.initial_capital)
    return BacktestResult(trades=trades, equity_curve=equity_curve, config=cfg, summary=summary)


def _summarize(trades: list[Trade], equity: pd.Series, initial: float) -> dict[str, float | int]:
    if not trades:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "ending_equity": initial,
            "return_pct": 0.0,
        }
    pnls = np.array([t.pnl_net for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = abs(losses.sum()) if len(losses) else 0.0
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    rolling_max = equity.cummax()
    dd = (equity - rolling_max) / rolling_max
    ending = float(equity.iloc[-1])
    return {
        "trade_count": len(trades),
        "win_rate": float((pnls > 0).mean() * 100),
        "profit_factor": float(pf),
        "total_pnl": float(pnls.sum()),
        "avg_pnl": float(pnls.mean()),
        "max_drawdown_pct": float(dd.min() * 100),
        "ending_equity": ending,
        "return_pct": float((ending / initial - 1) * 100),
    }
