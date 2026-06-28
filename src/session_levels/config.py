from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SessionLevelsConfig:
    """Defaults mirror tradingview/Session_Levels_Strategy.pine inputs."""

    trade_qty: int = 5
    one_trade_per_day: bool = False
    stop_buffer_ticks: int = 2
    trail_lookback: int = 3
    trail_activate_rr: float = 2.0
    rr_ratio: float = 3.0
    partial_exit_rr: float = 2.0
    partial_exit_pct: float = 50.0
    wait_for_or: bool = True
    or_minutes: int = 15
    entry_start_hour_et: int = 10
    entry_start_minute_et: int = 0
    entry_end_hour_ct: int = 14
    entry_end_minute_ct: int = 0
    loss_cooldown: int = 10
    same_dir_cooldown: int = 20
    use_skip_first_reclaim_after_win: bool = True
    use_ghost_fail_cooldown: bool = True
    opp_body_pct: float = 0.60
    opp_body_pct_short: float = 0.70
    skip_after_opposite_setup: bool = True
    flatten_at_2pm: bool = True
    use_daily_loss_cap: bool = True
    max_daily_loss_usd: float = 1200.0
    use_loss_streak_pause: bool = False
    loss_streak_days: int = 2
    recovery_win_days: int = 2
    require_fresh_cross: bool = True
    max_vwap_dist_pts: float = 50.0
    skip_flat_vwaps: bool = True
    vwap_slope_lookback: int = 6
    max_vwap_spread_pts: float = 20.0
    max_vwap_slope_pts: float = 15.0
    max_entry_risk_pts: float = 80.0
    skip_us_holidays: bool = True
    skip_fomc_days: bool = True
    tick_size: float = 0.25
    point_value: float = 2.0  # per contract (MNQ)
    initial_capital: float = 50_000.0
