#!/usr/bin/env python3
"""Grid-search Session Levels strategy parameters (90-day target)."""

from __future__ import annotations

import itertools
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import asdict, fields
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from session_levels.backtest import run_backtest
from session_levels.config import SessionLevelsConfig

# TradingView 90d baseline (must beat)
BASELINE_PNL = 19_553.50
BASELINE_TRADES = 64
BASELINE_WIN = 70.31
BASELINE_PF = 3.685
BASELINE_DD = 1_691.0

_DF: pd.DataFrame | None = None


def fetch_90d_5m(symbol: str = "NQ=F") -> pd.DataFrame:
    """Fetch ~90d of 5m bars in two yfinance chunks (60d max per request)."""
    ticker = yf.Ticker(symbol)
    df1 = ticker.history(period="60d", interval="5m", auto_adjust=False)
    df2 = ticker.history(period="30d", interval="5m", auto_adjust=False)
    for df in (df1, df2):
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [str(c[0]).lower() for c in df.columns]
        df.rename(
            columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            },
            inplace=True,
        )
    out = pd.concat([df1, df2])
    out = out.loc[:, ["open", "high", "low", "close", "volume"]]
    out.index = pd.to_datetime(out.index)
    if out.index.tz is None:
        out.index = out.index.tz_localize("America/New_York")
    else:
        out.index = out.index.tz_convert("America/New_York")
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")].dropna()
    cutoff = pd.Timestamp.now(tz="America/New_York") - pd.Timedelta(days=90)
    return out[out.index >= cutoff]


def round_trip_summary(trades, equity, initial: float) -> dict:
    grouped: dict[tuple, float] = {}
    for t in trades:
        key = (t.entry_time, t.side)
        grouped[key] = grouped.get(key, 0.0) + t.pnl_net
    pnls = list(grouped.values())
    total_pnl = sum(pnls)
    wins = sum(1 for p in pnls if p > 0)
    total = len(pnls)
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_win / gross_loss if gross_loss > 0 else 999.0
    rolling_max = equity.cummax()
    dd_usd = float(abs((equity - rolling_max).min()))
    return {
        "total_pnl": total_pnl,
        "return_pct": (equity.iloc[-1] / initial - 1) * 100,
        "round_trips": total,
        "win_rate": wins / total * 100 if total else 0,
        "profit_factor": pf,
        "max_dd_usd": dd_usd,
        "exit_legs": len(trades),
    }


def run_cfg(overrides: dict) -> dict:
    assert _DF is not None
    cfg = SessionLevelsConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    result = run_backtest(_DF, cfg)
    s = round_trip_summary(result.trades, result.equity_curve, cfg.initial_capital)
    return {**overrides, **s}


def init_worker(df: pd.DataFrame) -> None:
    global _DF
    _DF = df


def baseline() -> dict:
    return run_cfg({})


def build_grids() -> list[dict]:
    """Coarse then meaningful ranges around current defaults."""
    grid = {
        "trail_lookback": [2, 3, 4, 5],
        "trail_activate_rr": [1.5, 2.0, 2.5, 3.0],
        "rr_ratio": [2.5, 3.0, 3.5, 4.0],
        "partial_exit_rr": [1.5, 2.0, 2.5, 3.0],
        "partial_exit_pct": [40.0, 50.0, 60.0],
        "loss_cooldown": [5, 10, 15, 0],
        "same_dir_cooldown": [10, 20, 30, 0],
        "max_vwap_spread_pts": [15.0, 20.0, 25.0, 30.0],
        "max_entry_risk_pts": [60.0, 80.0, 100.0, 0],
        "opp_body_pct": [0.0, 0.5, 0.6, 0.7],
        "opp_body_pct_short": [0.0, 0.6, 0.7, 0.8],
    }
    keys = list(grid.keys())
    combos = [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]
    return combos


def build_single_param_grids() -> list[dict]:
    """One parameter varied at a time from defaults — faster first pass."""
    defaults = asdict(SessionLevelsConfig())
    sweeps = {
        "trail_lookback": [1, 2, 3, 4, 5, 6],
        "trail_activate_rr": [1.0, 1.5, 2.0, 2.5, 3.0],
        "rr_ratio": [2.0, 2.5, 3.0, 3.5, 4.0, 5.0],
        "partial_exit_rr": [1.0, 1.5, 2.0, 2.5, 3.0],
        "partial_exit_pct": [30.0, 40.0, 50.0, 60.0, 70.0],
        "loss_cooldown": [0, 5, 10, 15, 20],
        "same_dir_cooldown": [0, 10, 20, 30, 40],
        "max_vwap_spread_pts": [10.0, 15.0, 20.0, 25.0, 30.0, 0],
        "max_vwap_dist_pts": [30.0, 40.0, 50.0, 60.0, 0],
        "max_entry_risk_pts": [50.0, 60.0, 80.0, 100.0, 0],
        "max_vwap_slope_pts": [10.0, 15.0, 20.0, 0],
        "vwap_slope_lookback": [4, 6, 8, 10],
        "opp_body_pct": [0.0, 0.5, 0.6, 0.7, 0.8],
        "opp_body_pct_short": [0.0, 0.6, 0.7, 0.8, 0.9],
        "stop_buffer_ticks": [0, 1, 2, 3, 4],
    }
    combos: list[dict] = []
    for param, values in sweeps.items():
        for v in values:
            o = {param: v}
            combos.append(o)
    # bool toggles
    for param in [
        "wait_for_or", "use_skip_first_reclaim_after_win",
        "skip_flat_vwaps",
        "flatten_at_2pm", "one_trade_per_day",
    ]:
        for v in [True, False]:
            combos.append({param: v})
    return combos


def beats_baseline(s: dict, min_trades: int = 50) -> bool:
    if s["round_trips"] < min_trades:
        return False
    if s["total_pnl"] <= BASELINE_PNL:
        return False
    if s["max_dd_usd"] > BASELINE_DD * 1.25:
        return False
    return True


def refine_around(best: dict) -> list[dict]:
    """Small neighborhood around best single-param winners."""
    refined: list[dict] = []
    base = {k: v for k, v in best.items() if k in {f.name for f in fields(SessionLevelsConfig)}}
    neighbors = {
        "trail_lookback": [-1, 0, 1],
        "trail_activate_rr": [-0.25, 0, 0.25],
        "rr_ratio": [-0.25, 0, 0.25, 0.5],
        "partial_exit_rr": [-0.25, 0, 0.25],
        "partial_exit_pct": [-10, 0, 10],
        "loss_cooldown": [-5, 0, 5],
        "same_dir_cooldown": [-10, 0, 10],
    }
    for param, deltas in neighbors.items():
        if param not in base:
            continue
        cur = base[param]
        for d in deltas:
            val = cur + d
            if param in ("trail_lookback", "loss_cooldown", "same_dir_cooldown"):
                val = max(0, int(val))
            o = dict(base)
            o[param] = val
            refined.append(o)
    # pairwise combos of top movers
    top_keys = [k for k in base if k in neighbors]
    for a, b in itertools.combinations(top_keys[:6], 2):
        o = dict(base)
        refined.append(o)
    return refined


def main() -> None:
    global _DF
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    print("Fetching 90d 5m data...", flush=True)
    _DF = fetch_90d_5m()
    print(f"Loaded {len(_DF)} bars ({_DF.index[0]} → {_DF.index[-1]})", flush=True)

    print("\n=== BASELINE (current Pine defaults) ===", flush=True)
    base = baseline()
    print(
        f"PnL ${base['total_pnl']:,.2f} | {base['round_trips']} trips | "
        f"Win {base['win_rate']:.1f}% | PF {base['profit_factor']:.2f} | DD ${base['max_dd_usd']:,.0f}",
        flush=True,
    )
    print(
        f"TV target:  PnL ${BASELINE_PNL:,.2f} | {BASELINE_TRADES} trips | "
        f"Win {BASELINE_WIN:.1f}% | PF {BASELINE_PF:.2f} | DD ${BASELINE_DD:,.0f}",
        flush=True,
    )

    combos = build_single_param_grids()
    workers = min(8, max(1, __import__("os").cpu_count() - 1))
    print(f"\nPhase 1: single-param sweep ({len(combos)} combos, {workers} workers)...", flush=True)

    rows: list[dict] = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker, initargs=(_DF,)) as pool:
        futures = {pool.submit(run_cfg, c): c for c in combos}
        for i, fut in enumerate(as_completed(futures), 1):
            rows.append(fut.result())
            if i % 50 == 0 or i == len(combos):
                print(f"  {i}/{len(combos)} ({time.time()-t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "session_optimize_phase1.csv", index=False)

    qualified = df[df["round_trips"] >= 40].copy()
    better = qualified[qualified["total_pnl"] > BASELINE_PNL].sort_values("total_pnl", ascending=False)

    print(f"\n=== Phase 1: configs beating TV baseline (${BASELINE_PNL:,.0f}) ===", flush=True)
    if better.empty:
        print("None yet — showing top 10 by PnL anyway:", flush=True)
        top = qualified.sort_values("total_pnl", ascending=False).head(10)
    else:
        top = better.head(15)
        print(f"Found {len(better)} improvements", flush=True)

    show_cols = [
        "total_pnl", "round_trips", "win_rate", "profit_factor", "max_dd_usd",
    ] + [c for c in df.columns if c not in {
        "total_pnl", "return_pct", "round_trips", "win_rate", "profit_factor",
        "max_dd_usd", "exit_legs",
    }]
    param_cols = [c for c in show_cols if c not in {
        "total_pnl", "round_trips", "win_rate", "profit_factor", "max_dd_usd",
    }]
    print(top[["total_pnl", "round_trips", "win_rate", "profit_factor", "max_dd_usd"] + param_cols[:8]].to_string(index=False), flush=True)

    # Phase 2: combine top single-param winners
    if not better.empty:
        best_row = better.iloc[0].to_dict()
        best_params = {k: best_row[k] for k in {f.name for f in fields(SessionLevelsConfig)} if k in best_row}
        print(f"\nPhase 2: refining around best (${best_row['total_pnl']:,.0f})...", flush=True)

        # Merge top 3 param changes
        merge_cfg = {}
        for _, row in better.head(5).iterrows():
            for k in {f.name for f in fields(SessionLevelsConfig)}:
                if k in row and row[k] != getattr(SessionLevelsConfig(), k):
                    merge_cfg[k] = row[k]
        combo_tests = [merge_cfg]
        combo_tests.extend(refine_around(merge_cfg))

        phase2_rows = [run_cfg(c) for c in combo_tests]
        pd.DataFrame(phase2_rows).to_csv(out_dir / "session_optimize_phase2.csv", index=False)
        p2 = pd.DataFrame(phase2_rows).sort_values("total_pnl", ascending=False)
        print(p2.head(5).to_string(index=False), flush=True)
        if p2.iloc[0]["total_pnl"] > best_row["total_pnl"]:
            best_row = p2.iloc[0].to_dict()

    best_overall = qualified.sort_values("total_pnl", ascending=False).iloc[0].to_dict()
    if not better.empty and better.iloc[0]["total_pnl"] > best_overall["total_pnl"]:
        best_overall = better.iloc[0].to_dict()

    print(f"\n=== BEST OVERALL ===", flush=True)
    print(
        f"PnL ${best_overall['total_pnl']:,.2f} (+${best_overall['total_pnl']-BASELINE_PNL:,.2f} vs TV) | "
        f"{best_overall['round_trips']} trips | Win {best_overall['win_rate']:.1f}% | "
        f"PF {best_overall['profit_factor']:.2f} | DD ${best_overall['max_dd_usd']:,.0f}",
        flush=True,
    )
    changes = {
        k: best_overall[k]
        for k in {f.name for f in fields(SessionLevelsConfig)}
        if k in best_overall and best_overall[k] != getattr(SessionLevelsConfig(), k)
    }
    print("Parameter changes from default:", changes, flush=True)
    pd.DataFrame([best_overall]).to_csv(out_dir / "session_optimize_best.csv", index=False)
    print(f"\nSaved → output/session_optimize_*.csv", flush=True)


if __name__ == "__main__":
    main()
