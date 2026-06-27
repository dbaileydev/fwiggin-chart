from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fvg.backtest import BacktestConfig, run_backtest as run_fvg_backtest, summarize_trades
from fvg.detector import detect_fvgs
from fvg.strategy import StrategyConfig, build_pending_setups
from session_levels.backtest import run_backtest as run_session_levels_backtest
from session_levels.config import SessionLevelsConfig

from .date_ranges import DateRangeKey, ResolvedRange, resolve_range
from .pine_parser import parse_pine


def _fetch_bars(symbol: str, resolved: ResolvedRange) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    period = resolved.yfinance_period or "60d"
    df = ticker.history(
        period=period,
        interval=resolved.interval,
        auto_adjust=False,
    )
    if df.empty:
        raise RuntimeError(
            f"No data for {symbol} ({resolved.interval}, {period})"
        )

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(col[0]).lower() for col in df.columns]
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    out = df.loc[:, ["open", "high", "low", "close", "volume"]].copy()
    out.index = pd.to_datetime(out.index)
    if out.index.tz is None:
        out.index = out.index.tz_localize("America/New_York")
    else:
        out.index = out.index.tz_convert("America/New_York")
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")].dropna()

    if resolved.start is not None:
        start = pd.Timestamp(resolved.start)
        if start.tzinfo is None:
            start = start.tz_localize("America/New_York")
        else:
            start = start.tz_convert("America/New_York")
        out = out[out.index >= start]
    if resolved.end is not None:
        end = pd.Timestamp(resolved.end)
        if end.tzinfo is None:
            end = end.tz_localize("America/New_York")
        else:
            end = end.tz_convert("America/New_York")
        out = out[out.index <= end]

    if out.empty:
        raise RuntimeError("No bars in selected date range")
    return out


def _is_session_levels(pine_source: str, strategy_name: str) -> bool:
    name = strategy_name.lower()
    if "session levels" in name:
        return True
    return "vwap cross strategy" in pine_source.lower() or "session vwap" in pine_source.lower()


def _round_trip_pnls(trades: list) -> list[float]:
    grouped: dict[tuple, float] = {}
    for t in trades:
        key = (t.entry_time, t.side)
        grouped[key] = grouped.get(key, 0.0) + t.pnl_net
    return list(grouped.values())


def _build_summary(
    trades: list,
    equity: pd.Series,
    initial_capital: float,
) -> dict:
    round_pnls = _round_trip_pnls(trades)
    pnls = np.array(round_pnls, dtype=float) if round_pnls else np.array([])

    # Per-leg stats for sharpe / avg (keeps partial-exit detail)
    leg_pnls = np.array([t.pnl_net for t in trades], dtype=float) if trades else np.array([])
    base = summarize_trades(trades, equity, initial_capital) if trades else {
        "trade_count": 0, "win_rate": 0.0, "avg_pnl": 0.0, "sharpe": 0.0,
    }

    rolling_max = equity.cummax()
    drawdown_usd = equity - rolling_max
    max_dd_usd = float(abs(drawdown_usd.min())) if len(drawdown_usd) else 0.0
    max_dd_pct = float((drawdown_usd / rolling_max).min() * 100) if len(rolling_max) else 0.0

    wins = int((pnls > 0).sum()) if len(pnls) else 0
    total = len(round_pnls)

    gross_win = float(pnls[pnls > 0].sum()) if len(pnls) else 0.0
    gross_loss = float(abs(pnls[pnls < 0].sum())) if len(pnls) else 0.0
    profit_factor = gross_win / gross_loss if gross_loss > 0 else 0.0

    total_pnl = float(pnls.sum()) if len(pnls) else 0.0
    return_pct = float((equity.iloc[-1] / initial_capital - 1) * 100) if len(equity) else 0.0

    return {
        "totalPnl": total_pnl,
        "totalPnlPct": return_pct,
        "maxDrawdownUsd": max_dd_usd,
        "maxDrawdownPct": abs(max_dd_pct),
        "profitableTradesPct": float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
        "profitableTrades": wins,
        "totalTrades": total,
        "profitFactor": profit_factor,
        "initialCapital": initial_capital,
        "endingEquity": float(equity.iloc[-1]) if len(equity) else initial_capital,
        "tradeCount": total,
        "winRate": float((pnls > 0).mean() * 100) if len(pnls) else 0.0,
        "avgPnl": float(pnls.mean()) if len(pnls) else 0.0,
        "sharpe": base["sharpe"],
        "exitLegs": len(leg_pnls),
    }


def _serialize_trades(trades: list) -> list[dict]:
    return [
        {
            "side": t.side,
            "entryTime": t.entry_time.isoformat(),
            "exitTime": t.exit_time.isoformat(),
            "entryPrice": t.entry_price,
            "exitPrice": t.exit_price,
            "pnlNet": t.pnl_net,
            "exitReason": t.exit_reason.value,
            "contracts": t.contracts,
        }
        for t in trades
    ]


def _serialize_equity(equity: pd.Series) -> list[dict]:
    deduped: dict[str, float] = {}
    for ts, val in equity.items():
        deduped[pd.Timestamp(ts).isoformat()] = float(val)
    return [
        {"time": ts, "equity": val}
        for ts, val in sorted(deduped.items())
    ]


def _serialize_trade_bars(trades: list) -> list[dict]:
    by_time: dict[str, float] = {}
    for t in trades:
        key = t.exit_time.isoformat()
        by_time[key] = by_time.get(key, 0.0) + t.pnl_net
    return [
        {
            "time": ts,
            "pnl": pnl,
            "color": "#26a69a" if pnl >= 0 else "#ef5350",
        }
        for ts, pnl in sorted(by_time.items())
    ]


def run_pine_backtest(
    pine_source: str,
    *,
    range_key: DateRangeKey = "90d",
    symbol: str = "NQ=F",
) -> dict:
    meta = parse_pine(pine_source)
    resolved = resolve_range(range_key)
    df = _fetch_bars(symbol, resolved)
    initial_capital = meta.initial_capital

    if _is_session_levels(pine_source, meta.strategy_name):
        sl_cfg = SessionLevelsConfig(initial_capital=initial_capital)
        result = run_session_levels_backtest(df, sl_cfg)
        execution_note = (
            f'Running Python port of "{meta.strategy_name}" '
            f"({resolved.interval} bars, ET session logic, {sl_cfg.trade_qty} contracts)."
        )
    else:
        fvg_cfg = {"min_gap_points": 8.0, "max_age_bars": 24}
        strategy_raw = {
            "fvg": fvg_cfg,
            "tick_size": 0.25,
            "entry_mode": "edge",
            "require_trend": True,
            "require_trend_at_entry": True,
            "trend_ema_period": 50,
            "trade_bullish": True,
            "trade_bearish": True,
            "one_trade_at_a_time": True,
            "stop_buffer_ticks": 2,
            "risk_reward": 1.5,
            "min_stop_points": 20.0,
            "require_rejection": True,
            "displacement": {
                "enabled": True,
                "atr_period": 14,
                "min_body_ratio": 0.6,
                "min_atr_multiple": 1.5,
            },
            "session": {
                "enabled": True,
                "start": "09:30",
                "end": "11:30",
                "timezone": "America/New_York",
            },
        }
        strategy_cfg = StrategyConfig.from_dict(strategy_raw)
        gaps = detect_fvgs(df, min_gap_points=fvg_cfg["min_gap_points"])
        setups = build_pending_setups(df, strategy_cfg, gaps)
        bt_cfg = BacktestConfig(
            initial_capital=initial_capital,
            risk_per_trade_pct=1.0,
            max_contracts=5,
            point_value=2.0,
            tick_size=0.25,
            commission_per_side=0.62,
            slippage_ticks=1,
        )
        result = run_fvg_backtest(df, setups, strategy_cfg, bt_cfg)
        execution_note = (
            f'Pine strategy "{meta.strategy_name}" has no Python port yet — '
            "results use the FVG engine on the same symbol and date range."
        )

    summary = _build_summary(result.trades, result.equity_curve, initial_capital)

    return {
        "strategyName": meta.strategy_name,
        "pineVersion": meta.version,
        "isStrategy": meta.is_strategy,
        "range": {
            "key": resolved.key,
            "label": resolved.label,
            "interval": resolved.interval,
            "barCount": len(df),
            "start": df.index[0].isoformat(),
            "end": df.index[-1].isoformat(),
        },
        "symbol": symbol,
        "summary": summary,
        "equityCurve": _serialize_equity(result.equity_curve),
        "tradeBars": _serialize_trade_bars(result.trades),
        "trades": _serialize_trades(result.trades),
        "executionNote": execution_note,
    }
