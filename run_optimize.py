#!/usr/bin/env python3
"""Grid-search MNQ FVG strategy parameters — cached + parallel."""

from __future__ import annotations

import itertools
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from fvg.backtest import BacktestConfig, run_backtest
from fvg.data import fetch_yfinance
from fvg.detector import detect_fvgs
from fvg.strategy import StrategyConfig, build_pending_setups

MIN_TRADES = 15
PROGRESS_EVERY = 50
SAVE_EVERY = 500

# Globals for worker processes (set per batch)
_DF: pd.DataFrame | None = None
_BASE_CFG: dict | None = None
_BT_CFG: BacktestConfig | None = None
_GAPS: dict[float, list] | None = None
_EMAS: dict[int, pd.Series] | None = None
_DISP: dict[tuple[float, float], set[int]] | None = None
_MID_STATS: dict[int, dict] | None = None


def load_config(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def confidence_score(summary: dict) -> float:
    trades = summary["trade_count"]
    if trades < MIN_TRADES:
        return -1.0
    win = summary["win_rate"] / 100.0
    pf = min(summary["profit_factor"], 5.0)
    dd_penalty = 1.0 + summary["max_drawdown_pct"] / 100.0
    sample_factor = min(1.0, trades / 30.0)
    return (win * 0.4 + (pf / 5.0) * 0.6) * sample_factor / dd_penalty


def precompute_mid_stats(df: pd.DataFrame, atr_period: int = 14) -> dict[int, dict]:
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(atr_period, min_periods=atr_period).mean()
    stats: dict[int, dict] = {}
    for formed in range(2, len(df)):
        mid = formed - 1
        o = float(df["open"].iloc[mid])
        h = float(df["high"].iloc[mid])
        l = float(df["low"].iloc[mid])
        c = float(df["close"].iloc[mid])
        rng = h - l
        body_ratio = abs(c - o) / rng if rng > 0 else 0.0
        atr_val = float(atr.iloc[mid])
        stats[formed] = {"range": rng, "body_ratio": body_ratio, "atr": atr_val}
    return stats


def displacement_bars(atr_mult: float, body_ratio: float) -> set[int]:
    assert _MID_STATS is not None
    key = (atr_mult, body_ratio)
    if key not in _DISP:
        valid = set()
        for formed, s in _MID_STATS.items():
            if s["body_ratio"] >= body_ratio and s["atr"] > 0 and s["range"] >= s["atr"] * atr_mult:
                valid.add(formed)
        _DISP[key] = valid
    return _DISP[key]


def run_combo(params: dict) -> dict:
    assert _DF is not None and _BASE_CFG is not None and _BT_CFG is not None
    assert _GAPS is not None and _EMAS is not None

    cfg = deepcopy(_BASE_CFG)
    cfg["fvg"]["min_gap_points"] = params["min_gap"]
    cfg["fvg"]["max_age_bars"] = params["max_age"]
    cfg["strategy"]["entry_mode"] = params["entry_mode"]
    cfg["strategy"]["risk_reward"] = params["rr"]
    cfg["strategy"]["min_stop_points"] = params["min_stop"]
    cfg["strategy"]["trend_ema_period"] = params["ema"]
    cfg["strategy"]["trade_bearish"] = params["trade_bearish"]
    cfg["strategy"]["require_rejection"] = params["rejection"]
    cfg["strategy"]["session"]["enabled"] = params["session"]
    cfg["strategy"]["session"]["end"] = params["session_end"]
    cfg["strategy"]["displacement"]["min_atr_multiple"] = params["atr_mult"]
    cfg["strategy"]["displacement"]["min_body_ratio"] = params["body_ratio"]

    gaps = _GAPS[params["min_gap"]]
    strategy_raw = cfg["strategy"]
    strategy_raw["fvg"] = cfg["fvg"]
    strategy_raw["tick_size"] = cfg["contract"]["tick_size"]
    strategy_cfg = StrategyConfig.from_dict(strategy_raw)
    setups = build_pending_setups(
        _DF,
        strategy_cfg,
        gaps,
        ema_series=_EMAS[params["ema"]],
        displacement_bars=displacement_bars(params["atr_mult"], params["body_ratio"]),
    )
    result = run_backtest(_DF, setups, strategy_cfg, _BT_CFG)
    return {**params, **result.summary, "setups": len(setups), "score": confidence_score(result.summary)}


def build_grids() -> list[dict]:
    grid = {
        "min_gap": [6, 8, 10, 12],
        "min_stop": [20, 25, 30],
        "entry_mode": ["ce", "edge"],
        "rr": [1.5, 2.0, 2.5, 3.0],
        "ema": [20, 50],
        "max_age": [24, 48],
        "atr_mult": [1.0, 1.25, 1.5],
        "body_ratio": [0.5, 0.6, 0.7],
        "rejection": [False, True],
        "session": [False, True],
        "session_end": ["11:30", "16:00"],
        "trade_bearish": [False, True],
    }
    keys = list(grid.keys())
    combos = []
    for values in itertools.product(*(grid[k] for k in keys)):
        p = dict(zip(keys, values))
        if not p["session"] and p["session_end"] != "11:30":
            continue
        combos.append(p)
    return combos


def save_best(base_cfg: dict, best: dict, path: Path) -> None:
    best_cfg = {
        "symbol": base_cfg["symbol"],
        "interval": base_cfg["interval"],
        "period": base_cfg["period"],
        "contract": base_cfg["contract"],
        "fvg": {"min_gap_points": best["min_gap"], "max_age_bars": int(best["max_age"])},
        "strategy": {
            "entry_mode": best["entry_mode"],
            "require_trend": True,
            "require_trend_at_entry": True,
            "trend_ema_period": int(best["ema"]),
            "trade_bullish": True,
            "trade_bearish": bool(best["trade_bearish"]),
            "one_trade_at_a_time": True,
            "stop_buffer_ticks": 2,
            "risk_reward": best["rr"],
            "min_stop_points": best["min_stop"],
            "require_rejection": bool(best["rejection"]),
            "displacement": {
                "enabled": True,
                "atr_period": 14,
                "min_body_ratio": best["body_ratio"],
                "min_atr_multiple": best["atr_mult"],
            },
            "session": {
                "enabled": bool(best["session"]),
                "start": "09:30",
                "end": best["session_end"],
                "timezone": "America/New_York",
            },
        },
        "backtest": base_cfg["backtest"],
    }
    with path.open("w") as f:
        yaml.dump(best_cfg, f, default_flow_style=False, sort_keys=False)


def show_top(label: str, frame: pd.DataFrame, n: int = 10) -> None:
    print(f"\n{'=' * 72}\nTOP {n} — {label}\n{'=' * 72}", flush=True)
    cols = [
        "min_gap", "min_stop", "entry_mode", "rr", "ema", "rejection",
        "session", "session_end", "trade_bearish", "atr_mult", "body_ratio",
        "trade_count", "win_rate", "profit_factor", "return_pct",
        "max_drawdown_pct", "avg_pnl", "score",
    ]
    print(frame[cols].head(n).to_string(index=False, float_format=lambda x: f"{x:.2f}"), flush=True)


def init_worker(df, base_cfg, bt_cfg, gaps, emas, mid_stats):
    global _DF, _BASE_CFG, _BT_CFG, _GAPS, _EMAS, _DISP, _MID_STATS
    _DF = df
    _BASE_CFG = base_cfg
    _BT_CFG = bt_cfg
    _GAPS = gaps
    _EMAS = emas
    _DISP = {}
    _MID_STATS = mid_stats


def main() -> None:
    global _DF, _BASE_CFG, _BT_CFG, _GAPS, _EMAS, _DISP, _MID_STATS

    base_cfg = load_config(ROOT / "config" / "default.yaml")
    out_dir = ROOT / "output"
    out_dir.mkdir(exist_ok=True)

    print("Fetching data...", flush=True)
    df = fetch_yfinance(base_cfg["symbol"], interval=base_cfg["interval"], period=base_cfg["period"])
    print(f"Loaded {len(df)} bars", flush=True)

    print("Pre-computing caches...", flush=True)
    gaps = {mg: detect_fvgs(df, min_gap_points=mg) for mg in [6, 8, 10, 12]}
    emas = {p: df["close"].ewm(span=p, adjust=False).mean() for p in [20, 50]}
    mid_stats = precompute_mid_stats(df)

    bt_cfg = BacktestConfig(
        initial_capital=base_cfg["backtest"]["initial_capital"],
        risk_per_trade_pct=base_cfg["backtest"]["risk_per_trade_pct"],
        max_contracts=base_cfg["backtest"]["max_contracts"],
        point_value=base_cfg["contract"]["point_value"],
        tick_size=base_cfg["contract"]["tick_size"],
        commission_per_side=base_cfg["contract"]["commission_per_side"],
        slippage_ticks=base_cfg["contract"]["slippage_ticks"],
    )

    combos = build_grids()
    workers = min(6, max(1, __import__("os").cpu_count() - 1))
    est_sec = len(combos) * 0.4 / workers
    print(f"\nRunning {len(combos):,} combinations with {workers} workers (~{est_sec/60:.0f} min est.)", flush=True)

    rows: list[dict] = []
    t0 = time.time()
    done = 0

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=init_worker,
        initargs=(df, base_cfg, bt_cfg, gaps, emas, mid_stats),
    ) as pool:
        futures = {pool.submit(run_combo, p): p for p in combos}
        for fut in as_completed(futures):
            rows.append(fut.result())
            done += 1
            if done % PROGRESS_EVERY == 0 or done == len(combos):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(combos) - done) / rate if rate > 0 else 0
                print(
                    f"  {done:,}/{len(combos):,} ({100*done/len(combos):.1f}%) "
                    f"elapsed {elapsed:.0f}s ETA {eta:.0f}s",
                    flush=True,
                )
            if done % SAVE_EVERY == 0:
                pd.DataFrame(rows).to_csv(out_dir / "optimize_progress.csv", index=False)

    results = pd.DataFrame(rows)
    qualified = results[results["trade_count"] >= MIN_TRADES].copy()
    results.to_csv(out_dir / "optimize_all.csv", index=False)
    qualified.to_csv(out_dir / "optimize_qualified.csv", index=False)

    if qualified.empty:
        print("\nNo configs met minimum trade count. Try lowering MIN_TRADES.", flush=True)
        return

    by_score = qualified.sort_values("score", ascending=False)
    show_top("Confidence score", by_score)
    show_top("Profit factor", qualified.sort_values(["profit_factor", "win_rate"], ascending=False))
    show_top("Win rate", qualified.sort_values(["win_rate", "profit_factor"], ascending=False))

    best = by_score.iloc[0].to_dict()
    save_best(base_cfg, best, ROOT / "config" / "optimized.yaml")

    high_conf = qualified[(qualified["profit_factor"] >= 1.5) & (qualified["win_rate"] >= 50)]
    if not high_conf.empty:
        hc = high_conf.sort_values(["win_rate", "profit_factor"], ascending=False).iloc[0]
        save_best(base_cfg, hc.to_dict(), ROOT / "config" / "optimized_high_winrate.yaml")

    print(f"\nDone in {time.time() - t0:.0f}s", flush=True)
    print(f"Saved → output/optimize_qualified.csv", flush=True)
    print(f"Saved → config/optimized.yaml", flush=True)
    print(f"\n★ BEST OVERALL (score {best['score']:.3f})", flush=True)
    print(
        f"  gap={best['min_gap']} stop={best['min_stop']} entry={best['entry_mode']} rr={best['rr']} "
        f"ema={int(best['ema'])} reject={best['rejection']} session={best['session']} "
        f"end={best['session_end']} shorts={best['trade_bearish']}",
        flush=True,
    )
    print(
        f"  Trades={int(best['trade_count'])} Win={best['win_rate']:.1f}% PF={best['profit_factor']:.2f} "
        f"Return={best['return_pct']:.1f}% MaxDD={best['max_drawdown_pct']:.1f}%",
        flush=True,
    )


if __name__ == "__main__":
    main()
