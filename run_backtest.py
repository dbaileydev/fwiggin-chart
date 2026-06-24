#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from fvg.backtest import BacktestConfig, run_backtest
from fvg.data import fetch_yfinance, load_csv
from fvg.detector import detect_fvgs
from fvg.strategy import StrategyConfig, build_pending_setups


def load_config(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f)


def print_summary(summary: dict, gaps_found: int, setups_found: int) -> None:
    print("\n=== MNQ Fair Value Gap Backtest ===")
    print(f"FVGs detected:     {gaps_found}")
    print(f"Trade setups:        {setups_found}")
    print(f"Trades taken:        {summary['trade_count']}")
    print(f"Win rate:            {summary['win_rate']:.1f}%")
    print(f"Profit factor:       {summary['profit_factor']:.2f}")
    print(f"Total PnL:           ${summary['total_pnl']:,.2f}")
    print(f"Avg PnL / trade:     ${summary['avg_pnl']:,.2f}")
    print(f"Return:              {summary['return_pct']:.2f}%")
    print(f"Max drawdown:        {summary['max_drawdown_pct']:.2f}%")
    print(f"Sharpe (per trade):  {summary['sharpe']:.2f}")
    print(f"Ending equity:       ${summary['ending_equity']:,.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest MNQ fair value gap strategy")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "default.yaml",
        help="Path to YAML config",
    )
    parser.add_argument("--csv", type=Path, help="Optional CSV with OHLCV data")
    parser.add_argument("--save-trades", type=Path, help="Write trade log CSV")
    parser.add_argument("--save-equity", type=Path, help="Write equity curve CSV")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.csv:
        df = load_csv(args.csv)
        print(f"Loaded {len(df)} bars from {args.csv}")
    else:
        df = fetch_yfinance(
            cfg["symbol"],
            interval=cfg["interval"],
            period=cfg["period"],
        )
        print(
            f"Fetched {len(df)} bars for {cfg['symbol']} "
            f"({cfg['interval']}, {cfg['period']})"
        )

    fvg_cfg = cfg.get("fvg", {})
    gaps = detect_fvgs(df, min_gap_points=fvg_cfg.get("min_gap_points", 2.0))

    strategy_raw = cfg.get("strategy", {})
    strategy_raw["fvg"] = fvg_cfg
    strategy_raw["tick_size"] = cfg.get("contract", {}).get("tick_size", 0.25)
    strategy_cfg = StrategyConfig.from_dict(strategy_raw)

    setups = build_pending_setups(df, strategy_cfg, gaps)

    contract = cfg.get("contract", {})
    bt_raw = cfg.get("backtest", {})
    bt_cfg = BacktestConfig(
        initial_capital=bt_raw.get("initial_capital", 50_000),
        risk_per_trade_pct=bt_raw.get("risk_per_trade_pct", 1.0),
        max_contracts=bt_raw.get("max_contracts", 5),
        point_value=contract.get("point_value", 2.0),
        tick_size=contract.get("tick_size", 0.25),
        commission_per_side=contract.get("commission_per_side", 0.62),
        slippage_ticks=contract.get("slippage_ticks", 1),
    )

    result = run_backtest(df, setups, strategy_cfg, bt_cfg)
    print_summary(result.summary, len(gaps), len(setups))

    if result.trades:
        print("\nLast 5 trades:")
        for trade in result.trades[-5:]:
            print(
                f"  {trade.entry_time} {trade.side:5} "
                f"entry={trade.entry_price:.2f} exit={trade.exit_price:.2f} "
                f"pnl=${trade.pnl_net:,.2f} ({trade.exit_reason.value})"
            )

    if args.save_trades:
        import pandas as pd

        rows = [
            {
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "stop_price": t.stop_price,
                "target_price": t.target_price,
                "contracts": t.contracts,
                "pnl_net": t.pnl_net,
                "exit_reason": t.exit_reason.value,
                "gap_formed_at": t.gap_formed_at,
                "bars_held": t.bars_held,
            }
            for t in result.trades
        ]
        pd.DataFrame(rows).to_csv(args.save_trades, index=False)
        print(f"\nSaved trades to {args.save_trades}")

    if args.save_equity:
        result.equity_curve.to_csv(args.save_equity, header=True)
        print(f"Saved equity curve to {args.save_equity}")


if __name__ == "__main__":
    main()
