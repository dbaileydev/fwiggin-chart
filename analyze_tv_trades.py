#!/usr/bin/env python3
"""Analyze TradingView List of Trades export with PDH/PDL/ONH/ONL entry comments."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

LEVEL_RE = re.compile(
    r"PDH=([\d.]+|na)\s+PDL=([\d.]+|na)\s+ONH=([\d.]+|na)\s+ONL=([\d.]+|na)"
)


def parse_levels(comment: str) -> dict[str, float | None]:
    if not isinstance(comment, str):
        return {"pdh": None, "pdl": None, "onh": None, "onl": None}
    m = LEVEL_RE.search(comment)
    if not m:
        return {"pdh": None, "pdl": None, "onh": None, "onl": None}

    def to_float(v: str) -> float | None:
        return None if v == "na" else float(v)

    return {
        "pdh": to_float(m.group(1)),
        "pdl": to_float(m.group(2)),
        "onh": to_float(m.group(3)),
        "onl": to_float(m.group(4)),
    }


def load_tv_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]

    # Normalize common TV column names
    rename = {}
    for col in df.columns:
        if col.startswith("trade"):
            rename[col] = "trade_num"
        elif "date" in col and "time" in col:
            rename[col] = "datetime"
        elif col == "signal":
            rename[col] = "signal"
        elif col.startswith("price"):
            rename[col] = "price"
        elif "position size (qty)" in col or col == "qty":
            rename[col] = "qty"
        elif col.startswith("p&l usd") or col == "pnl":
            rename[col] = "pnl"
        elif col == "type":
            rename[col] = "type"
        elif "comment" in col:
            rename[col] = "comment"
    df = df.rename(columns=rename)

    required = {"trade_num", "type", "datetime", "signal", "price", "pnl"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns {missing}. Found: {list(df.columns)}")

    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df["trade_num"] = pd.to_numeric(df["trade_num"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")

    entries = df[df["type"].str.lower().str.contains("entry", na=False)].copy()
    exits = df[df["type"].str.lower().str.contains("exit", na=False)].copy()

    if entries.empty:
        raise ValueError("No entry rows found. Export List of Trades from Strategy Tester.")

    comment_col = "comment" if "comment" in entries.columns else None
    if comment_col:
        levels = entries[comment_col].apply(parse_levels).apply(pd.Series)
        entries = pd.concat([entries, levels], axis=1)
    else:
        for c in ("pdh", "pdl", "onh", "onl"):
            entries[c] = None

    exit_pnl = exits.groupby("trade_num")["pnl"].sum().rename("trade_pnl")
    exit_signal = exits.groupby("trade_num")["signal"].last().rename("exit_signal")

    trades = entries.set_index("trade_num").join(exit_pnl).join(exit_signal)
    trades = trades.dropna(subset=["trade_pnl"])
    trades["win"] = trades["trade_pnl"] > 0
    trades["direction"] = trades["signal"].str.contains("Long", case=False, na=False).map(
        {True: "long", False: "short"}
    )
    trades["hour"] = trades["datetime"].dt.hour + trades["datetime"].dt.minute / 60

    def bucket(h: float) -> str:
        if h < 10.5:
            return "9:35–10:30"
        if h < 12.0:
            return "10:30–12:00"
        if h < 14.0:
            return "12:00–14:00"
        return "14:00–16:00"

    trades["time_bucket"] = trades["hour"].apply(bucket)

    for level in ("pdh", "pdl", "onh", "onl"):
        trades[f"above_{level}"] = trades["price"] > trades[level]
        trades[f"below_{level}"] = trades["price"] < trades[level]
        trades[f"dist_{level}"] = trades["price"] - trades[level]

    trades["or_range"] = trades["pdh"] - trades["pdl"]
    trades["on_range"] = trades["onh"] - trades["onl"]

    return trades.reset_index()


def win_rate_table(trades: pd.DataFrame, group_col: str, min_n: int = 5) -> pd.DataFrame:
    g = trades.groupby(group_col, dropna=False)
    out = g.agg(
        trades=("win", "count"),
        wins=("win", "sum"),
        total_pnl=("trade_pnl", "sum"),
        avg_pnl=("trade_pnl", "mean"),
    )
    out["win_rate"] = (out["wins"] / out["trades"] * 100).round(1)
    out = out[out["trades"] >= min_n].sort_values("win_rate", ascending=False)
    return out


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def analyze(trades: pd.DataFrame) -> None:
    n = len(trades)
    wins = trades["win"].sum()
    total_pnl = trades["trade_pnl"].sum()

    print_section("Overview")
    print(f"Trades:     {n}")
    print(f"Win rate:   {wins / n * 100:.1f}%")
    print(f"Total PnL:  ${total_pnl:,.2f}")
    print(f"Avg PnL:    ${trades['trade_pnl'].mean():,.2f}")
    print(f"Long/Short: {trades['direction'].value_counts().to_dict()}")

    print_section("By direction")
    print(win_rate_table(trades, "direction").to_string())

    print_section("By time of day")
    print(win_rate_table(trades, "time_bucket").to_string())

    print_section("Entry vs PDH / PDL")
    for col, label in [("above_pdh", "Above PDH"), ("below_pdl", "Below PDL")]:
        sub = trades.dropna(subset=[col.replace("above_", "").replace("below_", "")])
        if not sub.empty:
            print(f"\n{label}:")
            print(win_rate_table(sub, col, min_n=3).to_string())

    print_section("Entry vs ONH / ONL")
    for col, label in [("above_onh", "Above ONH"), ("below_onl", "Below ONL")]:
        lvl = col.split("_")[1]
        sub = trades.dropna(subset=[lvl])
        if not sub.empty:
            print(f"\n{label}:")
            print(win_rate_table(sub, col, min_n=3).to_string())

    print_section("ORB breakout context (long above PDH / short below PDL)")
    longs = trades[trades["direction"] == "long"].dropna(subset=["pdh"])
    shorts = trades[trades["direction"] == "short"].dropna(subset=["pdl"])
    if len(longs) >= 3:
        longs = longs.copy()
        longs["ctx"] = longs["above_pdh"].map({True: "Long above PDH", False: "Long below PDH"})
        print("\nLongs:")
        print(win_rate_table(longs, "ctx", min_n=3).to_string())
    if len(shorts) >= 3:
        shorts = shorts.copy()
        shorts["ctx"] = shorts["below_pdl"].map({True: "Short below PDL", False: "Short above PDL"})
        print("\nShorts:")
        print(win_rate_table(shorts, "ctx", min_n=3).to_string())

    print_section("Overnight range position at entry")
    sub = trades.dropna(subset=["onh", "onl"]).copy()
    if len(sub) >= 5:
        sub["on_ctx"] = "Inside ON range"
        sub.loc[sub["above_onh"], "on_ctx"] = "Above ONH"
        sub.loc[sub["below_onl"], "on_ctx"] = "Below ONL"
        print(win_rate_table(sub, "on_ctx").to_string())

    print_section("Exit reasons (top signals)")
    exits = trades["exit_signal"].fillna("unknown").str.extract(
        r"(Opp FVG Exit|FVG TP|BE Stop|Stop|RTH Close)", expand=False
    )
    trades = trades.copy()
    trades["exit_type"] = exits.fillna(trades["exit_signal"].str[:30])
    print(win_rate_table(trades, "exit_type", min_n=3).to_string())

    print_section("Distance from key levels (avg pts, winners vs losers)")
    for lvl in ("pdh", "pdl", "onh", "onl"):
        col = f"dist_{lvl}"
        s = trades.dropna(subset=[col])
        if s.empty:
            continue
        w = s[s["win"]][col].mean()
        l = s[~s["win"]][col].mean()
        print(f"{lvl.upper():>3}  winners avg dist: {w:+.2f}  |  losers avg dist: {l:+.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze TradingView ORB trade export")
    parser.add_argument(
        "csv",
        nargs="?",
        default="output/tv_trades.csv",
        help="Path to TradingView List of Trades CSV",
    )
    args = parser.parse_args()

    path = Path(args.csv)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        print("\nExport from TradingView: Strategy Tester → List of Trades → download CSV")
        print(f"Save as: {Path('output/tv_trades.csv').resolve()}")
        return 1

    trades = load_tv_trades(path)
    if trades[["pdh", "pdl", "onh", "onl"]].isna().all(axis=None):
        print("Warning: no PDH/PDL/ONH/ONL found in entry comments.", file=sys.stderr)
        print("Re-export after updating the Pine script with formatKeyLevels().", file=sys.stderr)

    analyze(trades)
    out = path.with_name(path.stem + "_analysis.csv")
    trades.to_csv(out, index=False)
    print(f"\nEnriched trades saved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
