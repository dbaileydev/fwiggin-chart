#!/usr/bin/env python3
"""Compare winning TV trades vs session price action — how much move was left?"""

from __future__ import annotations

import argparse
from datetime import time as dt_time
from pathlib import Path

import pandas as pd
import yfinance as yf

TZ = "America/New_York"
TZ_CT = "America/Chicago"
RTH_OPEN = dt_time(9, 30)
RTH_CLOSE = dt_time(16, 0)
OR_MINUTES = 15
TICK = 0.25
STOP_BUF = 2 * TICK
POINT_VALUE = 2.0  # MNQ per point (10 contracts in user's export)


def load_grouped_trades(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(path)
    df = df.rename(columns={
        "Trade number": "trade_num",
        "Type": "type",
        "Date and time": "datetime",
        "Signal": "signal",
        "Price USD": "price",
        "Net PnL USD": "pnl",
        "Favorable excursion USD": "mfe",
    })
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["is_entry"] = df["type"].str.contains("Entry")
    df["is_exit"] = df["type"].str.contains("Exit")

    entries = df[df["is_entry"]][["trade_num", "datetime", "signal", "price"]].rename(
        columns={"datetime": "entry_time", "signal": "direction", "price": "entry_px"}
    )
    exits = df[df["is_exit"]][["trade_num", "datetime", "signal", "price", "pnl", "mfe"]].rename(
        columns={
            "datetime": "exit_time",
            "signal": "exit_signal",
            "price": "exit_px",
            "pnl": "leg_pnl",
            "mfe": "leg_mfe",
        }
    )
    legs = entries.merge(exits, on="trade_num")

    trades = (
        legs.groupby(["entry_time", "direction"])
        .agg(
            entry_px=("entry_px", "first"),
            legs=("trade_num", "count"),
            total_pnl=("leg_pnl", "sum"),
            exit_types=("exit_signal", lambda s: " + ".join(s)),
            last_exit_time=("exit_time", "max"),
            last_exit_px=("exit_px", "last"),
            max_leg_mfe=("leg_mfe", "max"),
        )
        .reset_index()
    )
    trades["win"] = trades["total_pnl"] > 0
    return trades, legs


def fetch_bars() -> pd.DataFrame:
    df = yf.Ticker("NQ=F").history(period="60d", interval="5m", auto_adjust=False)
    df = df.rename(columns=str.lower)
    df.index = df.index.tz_convert(TZ)
    return df


def is_rth(ts: pd.Timestamp) -> bool:
    if ts.weekday() >= 5:
        return False
    t = ts.time()
    return RTH_OPEN <= t < RTH_CLOSE


def session_levels_for_day(bars: pd.DataFrame, day) -> dict:
    day_bars = bars[bars.index.date == day]
    rth = day_bars[[is_rth(ts) for ts in day_bars.index]]
    if rth.empty:
        return {}

    sess_open = rth.index[0].replace(hour=9, minute=30, second=0, microsecond=0)
    or_end = sess_open + pd.Timedelta(minutes=OR_MINUTES)
    or_bars = rth[(rth.index >= sess_open) & (rth.index < or_end)]
    or_high = or_bars["high"].max() if not or_bars.empty else float("nan")
    or_low = or_bars["low"].min() if not or_bars.empty else float("nan")

    # Prior RTH from previous trading day in sample
    prior_days = bars[bars.index.date < day]
    pd_high = pd_low = float("nan")
    if not prior_days.empty:
        last_day = prior_days.index.date[-1]
        prev_rth = prior_days[[is_rth(ts) for ts in prior_days.index]]
        prev_rth = prev_rth[prev_rth.index.date == last_day]
        if not prev_rth.empty:
            pd_high = prev_rth["high"].max()
            pd_low = prev_rth["low"].min()

    # Overnight before today's RTH
    pre = day_bars[day_bars.index < sess_open]
    on_high = pre["high"].max() if not pre.empty else float("nan")
    on_low = pre["low"].min() if not pre.empty else float("nan")

    return {
        "or_high": or_high,
        "or_low": or_low,
        "pd_high": pd_high,
        "pd_low": pd_low,
        "on_high": on_high,
        "on_low": on_low,
    }


def match_entry_bar(bars: pd.DataFrame, dt: pd.Timestamp, entry_px: float) -> pd.Timestamp | None:
    for tz in (TZ, TZ_CT):
        t = dt.tz_localize(tz) if dt.tzinfo is None else dt.tz_convert(tz)
        t = t.tz_convert(TZ)
        day_bars = bars[bars.index.date == t.date()]
        if day_bars.empty:
            continue
        cands = day_bars[(day_bars.index.hour == t.hour) & (day_bars.index.minute == t.minute)]
        if cands.empty:
            idx = (day_bars.index - t).abs().argsort()[:3]
            cands = day_bars.iloc[idx]
        for ts, row in cands.iterrows():
            if abs(row["close"] - entry_px) < 25:
                return ts
    return None


def analyze_winner(trade: pd.Series, bars: pd.DataFrame) -> dict:
    entry_time = trade["entry_time"]
    direction = trade["direction"].lower()
    entry_px = trade["entry_px"]
    bar_ts = match_entry_bar(bars, entry_time, entry_px)
    if bar_ts is None:
        return {"error": "no bar match"}

    row = bars.loc[bar_ts]
    if direction == "long":
        stop_px = row["low"] - STOP_BUF
        risk = entry_px - stop_px
    else:
        stop_px = row["high"] + STOP_BUF
        risk = stop_px - entry_px
    if risk <= 0:
        return {"error": "bad risk"}

    day = bar_ts.date()
    levels = session_levels_for_day(bars, day)

    # Session window: entry bar → RTH close (or 2PM CT = 3PM ET for flatten reference)
    flatten_et = bar_ts.replace(hour=15, minute=0, second=0, microsecond=0)
    sess_end = bar_ts.replace(hour=16, minute=0, second=0, microsecond=0)
    fwd = bars.loc[bar_ts:]
    fwd = fwd[(fwd.index.date == day) & (fwd.index <= sess_end)]

    if direction == "long":
        session_extreme = fwd["high"].max()
        session_extreme_time = fwd["high"].idxmax()
        exit_px = trade["last_exit_px"]
        mfe_pts = session_extreme - entry_px
        exit_pts = exit_px - entry_px
        left_pts = session_extreme - exit_px
    else:
        session_extreme = fwd["low"].min()
        session_extreme_time = fwd["low"].idxmin()
        exit_px = trade["last_exit_px"]
        mfe_pts = entry_px - session_extreme
        exit_pts = entry_px - exit_px
        left_pts = exit_px - session_extreme

    mfe_r = mfe_pts / risk
    exit_r = exit_pts / risk
    left_r = left_pts / risk

    # Best favorable before 2PM ET flatten window
    fwd_flat = fwd[fwd.index <= flatten_et]
    if not fwd_flat.empty:
        if direction == "long":
            pre2pm_ext = fwd_flat["high"].max()
            pre2pm_pts = pre2pm_ext - entry_px
        else:
            pre2pm_ext = fwd_flat["low"].min()
            pre2pm_pts = entry_px - pre2pm_ext
        pre2pm_r = pre2pm_pts / risk
    else:
        pre2pm_r = float("nan")

    # Level tags at session extreme
    def near_level(extreme: float, lvl: float, tol: float = 5.0) -> bool:
        return pd.notna(lvl) and abs(extreme - lvl) <= tol

    lvl = levels
    if direction == "long":
        tags = []
        for name, key in [("ORH", "or_high"), ("ONH", "on_high"), ("PDH", "pd_high")]:
            if near_level(session_extreme, lvl.get(key, float("nan"))):
                tags.append(name)
    else:
        tags = []
        for name, key in [("ORL", "or_low"), ("ONL", "on_low"), ("PDL", "pd_low")]:
            if near_level(session_extreme, lvl.get(key, float("nan"))):
                tags.append(name)

    # Bars after exit until session extreme (did we exit too early?)
    last_exit = trade["last_exit_time"]
    last_exit_ts = last_exit.tz_localize(TZ_CT).tz_convert(TZ) if last_exit.tzinfo is None else last_exit.tz_convert(TZ)
    after_exit = fwd[fwd.index > last_exit_ts]
    if not after_exit.empty:
        if direction == "long":
            post_exit_move = after_exit["high"].max() - exit_px
        else:
            post_exit_move = exit_px - after_exit["low"].min()
    else:
        post_exit_move = 0.0

    # Rejection at session high bar (upper wick for longs)
    sh_bar = bars.loc[session_extreme_time]
    rng = sh_bar["high"] - sh_bar["low"]
    if direction == "long" and rng > 0:
        upper_wick = sh_bar["high"] - max(sh_bar["open"], sh_bar["close"])
        rejection = upper_wick / rng
        bearish_close = sh_bar["close"] < sh_bar["open"]
    elif direction == "short" and rng > 0:
        lower_wick = min(sh_bar["open"], sh_bar["close"]) - sh_bar["low"]
        rejection = lower_wick / rng
        bearish_close = sh_bar["close"] > sh_bar["open"]
    else:
        rejection = 0.0
        bearish_close = False

    return {
        "entry_time": str(entry_time),
        "direction": direction,
        "exit_types": trade["exit_types"],
        "total_pnl": trade["total_pnl"],
        "risk_pts": round(risk, 2),
        "mfe_r_session": round(mfe_r, 2),
        "exit_r": round(exit_r, 2),
        "left_r": round(left_r, 2),
        "left_pts": round(left_pts, 1),
        "post_exit_move_pts": round(post_exit_move, 1),
        "pre2pm_mfe_r": round(pre2pm_r, 2) if pd.notna(pre2pm_r) else None,
        "session_extreme": round(session_extreme, 2),
        "exit_px": round(exit_px, 2),
        "level_tags": ",".join(tags) if tags else "none",
        "extreme_rejection_wick": round(rejection, 2),
        "extreme_reversal_candle": bearish_close,
        "had_trail": "Trail Stop" in trade["exit_types"],
        "had_2pm": "2PM Flatten" in trade["exit_types"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "csv",
        nargs="?",
        default="/Users/daniel/Downloads/Session_Levels_CME_MINI_MNQ1!_2026-06-25 (5).csv",
    )
    args = parser.parse_args()

    trades, _ = load_grouped_trades(Path(args.csv))
    winners = trades[trades["win"]].copy()
    print(f"Loading NQ 5m bars...")
    bars = fetch_bars()

    results = []
    for _, t in winners.iterrows():
        results.append(analyze_winner(t, bars))

    df = pd.DataFrame([r for r in results if "error" not in r])
    err = sum(1 for r in results if "error" in r)
    print(f"\nWinners analyzed: {len(df)} ({err} skipped — no bar match)")

    if df.empty:
        return

    print("\n" + "=" * 72)
    print("CAPTURE RATE (session MFE vs last exit)")
    print("=" * 72)
    print(f"Avg exit R:        {df['exit_r'].mean():.2f}R")
    print(f"Avg session MFE:   {df['mfe_r_session'].mean():.2f}R")
    print(f"Avg left on table: {df['left_r'].mean():.2f}R ({df['left_pts'].mean():.1f} pts)")
    print(f"Median left:       {df['left_r'].median():.2f}R")
    print(f"Avg post-exit move (same session): {df['post_exit_move_pts'].mean():.1f} pts")

    trail = df[df["had_trail"]]
    flat = df[df["had_2pm"]]
    notrail = df[~df["had_trail"] & ~df["had_2pm"]]
    print(f"\nTrail exits ({len(trail)}): avg left {trail['left_r'].mean():.2f}R, post-exit {trail['post_exit_move_pts'].mean():.1f} pts")
    if len(flat):
        print(f"2PM flatten ({len(flat)}): avg left {flat['left_r'].mean():.2f}R")
    if len(notrail):
        print(f"Other ({len(notrail)}): avg left {notrail['left_r'].mean():.2f}R")

    print("\n" + "=" * 72)
    print("SESSION TOP LEVELS (within 5 pts of session extreme)")
    print("=" * 72)
    print(df["level_tags"].value_counts().head(10).to_string())

    print("\n" + "=" * 72)
    print("BIGGEST OPPORTUNITIES (most R left after exit)")
    print("=" * 72)
    top = df.nlargest(10, "left_r")
    for _, r in top.iterrows():
        print(
            f"  {r['entry_time'][:10]} {r['direction']:5} exit={r['exit_r']:.1f}R "
            f"session_mfe={r['mfe_r_session']:.1f}R left={r['left_r']:.1f}R "
            f"post={r['post_exit_move_pts']:.0f}pts | {r['exit_types']} | levels={r['level_tags']}"
        )

    print("\n" + "=" * 72)
    print("RECOMMENDATIONS DATA")
    print("=" * 72)
    # How often session extreme had rejection candle
    rej = df[df["extreme_rejection_wick"] >= 0.5]
    print(f"Session extreme had >=50% rejection wick: {len(rej)}/{len(df)} ({len(rej)/len(df)*100:.0f}%)")
    print(f"  avg left R when rejection at top: {rej['left_r'].mean():.2f}R")

    # Trades that hit >3R session but exited <2.5R
    big = df[(df["mfe_r_session"] >= 3) & (df["exit_r"] < 2.5)]
    print(f"\nSession MFE >=3R but exit <2.5R: {len(big)} trades")
    if len(big):
        print(f"  avg left: {big['left_r'].mean():.2f}R — trail likely too tight or partial-heavy")

    # 3:1 TP would have helped?
    hit3 = df[df["mfe_r_session"] >= 3]
    print(f"\nSession reached 3R+ after entry: {len(hit3)}/{len(df)} ({len(hit3)/len(df)*100:.0f}%)")
    print(f"  avg exit R on those: {hit3['exit_r'].mean():.2f}R")

    out = Path("output/winner_exit_analysis.csv")
    out.parent.mkdir(exist_ok=True)
    df.sort_values("left_r", ascending=False).to_csv(out, index=False)
    print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
