from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class ExitReason(str, Enum):
    STOP = "stop"
    TARGET = "target"
    END = "end_of_data"


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    contracts: int
    pnl_gross: float
    pnl_net: float
    exit_reason: ExitReason
    gap_formed_at: pd.Timestamp
    bars_held: int


@dataclass
class BacktestConfig:
    initial_capital: float = 50_000.0
    risk_per_trade_pct: float = 1.0
    max_contracts: int = 5
    point_value: float = 2.0
    tick_size: float = 0.25
    commission_per_side: float = 0.62
    slippage_ticks: int = 1


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    config: BacktestConfig
    summary: dict[str, float | int]


def _slippage_price(side: str, price: float, tick_size: float, slippage_ticks: int, adverse: bool) -> float:
    slip = slippage_ticks * tick_size
    if side == "long":
        return price + slip if adverse else price - slip
    return price - slip if adverse else price + slip


def _contracts_for_risk(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    point_value: float,
    max_contracts: int,
) -> int:
    risk_dollars = equity * (risk_pct / 100.0)
    stop_points = abs(entry - stop)
    if stop_points <= 0:
        return 0
    per_contract_risk = stop_points * point_value
    qty = int(risk_dollars // per_contract_risk)
    return max(0, min(qty, max_contracts))


def run_backtest(
    df: pd.DataFrame,
    setups,
    strategy_cfg,
    bt_cfg: BacktestConfig,
) -> BacktestResult:
    from .detector import FVGSide, is_fvg_invalidated, price_touches_gap
    from .strategy import PendingSetup, StrategyConfig

    assert isinstance(strategy_cfg, StrategyConfig)

    equity = bt_cfg.initial_capital
    equity_points: list[tuple[pd.Timestamp, float]] = []
    ema = df["close"].ewm(span=strategy_cfg.trend_ema_period, adjust=False).mean()

    active_setup: PendingSetup | None = None
    active_gap = None
    position: dict | None = None
    trades: list[Trade] = []

    setups_by_bar: dict[int, list[PendingSetup]] = {}
    for setup in setups:
        setups_by_bar.setdefault(setup.gap.formed_bar, []).append(setup)

    for i in range(len(df)):
        ts = pd.Timestamp(df.index[i])
        o = float(df["open"].iloc[i])
        h = float(df["high"].iloc[i])
        l = float(df["low"].iloc[i])
        c = float(df["close"].iloc[i])

        # Manage open position
        if position is not None:
            side = position["side"]
            stop = position["stop"]
            target = position["target"]
            exit_price = None
            reason = None

            if side == "long":
                if l <= stop:
                    exit_price = _slippage_price("long", stop, bt_cfg.tick_size, bt_cfg.slippage_ticks, adverse=True)
                    reason = ExitReason.STOP
                elif h >= target:
                    exit_price = _slippage_price("long", target, bt_cfg.tick_size, bt_cfg.slippage_ticks, adverse=False)
                    reason = ExitReason.TARGET
            else:
                if h >= stop:
                    exit_price = _slippage_price("short", stop, bt_cfg.tick_size, bt_cfg.slippage_ticks, adverse=True)
                    reason = ExitReason.STOP
                elif l <= target:
                    exit_price = _slippage_price("short", target, bt_cfg.tick_size, bt_cfg.slippage_ticks, adverse=False)
                    reason = ExitReason.TARGET

            if exit_price is not None and reason is not None:
                contracts = position["contracts"]
                direction = 1 if side == "long" else -1
                points = (exit_price - position["entry"]) * direction
                gross = points * bt_cfg.point_value * contracts
                commission = bt_cfg.commission_per_side * 2 * contracts
                net = gross - commission
                equity += net
                trades.append(
                    Trade(
                        side=side,
                        entry_time=position["entry_time"],
                        exit_time=ts,
                        entry_price=position["entry"],
                        exit_price=exit_price,
                        stop_price=stop,
                        target_price=target,
                        contracts=contracts,
                        pnl_gross=gross,
                        pnl_net=net,
                        exit_reason=reason,
                        gap_formed_at=position["gap_formed_at"],
                        bars_held=i - position["entry_bar"],
                    )
                )
                position = None
                active_setup = None
                active_gap = None

        # Invalidate active setup gap
        if active_gap is not None:
            if is_fvg_invalidated(active_gap, h, l):
                active_setup = None
                active_gap = None

        # Expire stale setups
        if active_setup is not None:
            age = i - active_setup.gap.formed_bar
            if age > strategy_cfg.max_age_bars:
                active_setup = None
                active_gap = None

        # Register new setups on this bar (after the impulse candle closes)
        if i in setups_by_bar and position is None:
            if not strategy_cfg.one_trade_at_a_time or active_setup is None:
                # Prefer most recent / largest gap on same bar
                candidate = max(setups_by_bar[i], key=lambda s: s.gap.size)
                active_setup = candidate
                active_gap = candidate.gap

        # Attempt entry when price taps the gap entry level
        if position is None and active_setup is not None and active_gap is not None:
            tapped = price_touches_gap(active_gap, h, l)
            entry_level = active_setup.entry_price
            entry_hit = l <= entry_level <= h

            if tapped and entry_hit:
                side = "long" if active_setup.side == FVGSide.BULLISH else "short"
                ema_val = float(ema.iloc[i])
                if strategy_cfg.require_trend_at_entry:
                    if side == "long" and c < ema_val:
                        continue
                    if side == "short" and c > ema_val:
                        continue

                if strategy_cfg.require_rejection:
                    if side == "long" and not (c > o and c >= entry_level):
                        continue
                    if side == "short" and not (c < o and c <= entry_level):
                        continue

                raw_entry = entry_level
                entry = _slippage_price(side, raw_entry, bt_cfg.tick_size, bt_cfg.slippage_ticks, adverse=True)
                contracts = _contracts_for_risk(
                    equity,
                    bt_cfg.risk_per_trade_pct,
                    entry,
                    active_setup.stop_price,
                    bt_cfg.point_value,
                    bt_cfg.max_contracts,
                )
                if contracts > 0:
                    position = {
                        "side": side,
                        "entry": entry,
                        "stop": active_setup.stop_price,
                        "target": active_setup.target_price,
                        "contracts": contracts,
                        "entry_time": ts,
                        "entry_bar": i,
                        "gap_formed_at": active_setup.gap.formed_at,
                    }

        equity_points.append((ts, equity))

    # Close any open trade at last bar
    if position is not None:
        last_ts = pd.Timestamp(df.index[-1])
        last_close = float(df["close"].iloc[-1])
        side = position["side"]
        exit_price = _slippage_price(side, last_close, bt_cfg.tick_size, bt_cfg.slippage_ticks, adverse=True)
        contracts = position["contracts"]
        direction = 1 if side == "long" else -1
        points = (exit_price - position["entry"]) * direction
        gross = points * bt_cfg.point_value * contracts
        commission = bt_cfg.commission_per_side * 2 * contracts
        net = gross - commission
        equity += net
        trades.append(
            Trade(
                side=side,
                entry_time=position["entry_time"],
                exit_time=last_ts,
                entry_price=position["entry"],
                exit_price=exit_price,
                stop_price=position["stop"],
                target_price=position["target"],
                contracts=contracts,
                pnl_gross=gross,
                pnl_net=net,
                exit_reason=ExitReason.END,
                gap_formed_at=position["gap_formed_at"],
                bars_held=len(df) - 1 - position["entry_bar"],
            )
        )
        equity_points[-1] = (last_ts, equity)

    equity_curve = pd.Series(
        data=[v for _, v in equity_points],
        index=pd.DatetimeIndex([t for t, _ in equity_points]),
        name="equity",
    )

    summary = summarize_trades(trades, equity_curve, bt_cfg.initial_capital)
    return BacktestResult(trades=trades, equity_curve=equity_curve, config=bt_cfg, summary=summary)


def summarize_trades(trades: list[Trade], equity: pd.Series, initial_capital: float) -> dict[str, float | int]:
    if not trades:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "ending_equity": initial_capital,
            "return_pct": 0.0,
        }

    pnls = np.array([t.pnl_net for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = abs(losses.sum()) if len(losses) else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = float(drawdown.min() * 100)

    trade_returns = pnls / initial_capital
    sharpe = 0.0
    if trade_returns.std(ddof=1) > 0:
        sharpe = float((trade_returns.mean() / trade_returns.std(ddof=1)) * np.sqrt(len(trade_returns)))

    ending = float(equity.iloc[-1])
    return {
        "trade_count": len(trades),
        "win_rate": float((pnls > 0).mean() * 100),
        "profit_factor": float(profit_factor),
        "total_pnl": float(pnls.sum()),
        "avg_pnl": float(pnls.mean()),
        "max_drawdown_pct": max_dd,
        "sharpe": sharpe,
        "ending_equity": ending,
        "return_pct": float((ending / initial_capital - 1) * 100),
    }
