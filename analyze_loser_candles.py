#!/usr/bin/env python3
"""Analyze losing TV trades against OHLCV + session/prior-day VWAP."""

from __future__ import annotations

import argparse
from datetime import time as dt_time
from pathlib import Path

import pandas as pd
import yfinance as yf

TZ = "America/New_York"
RTH_OPEN = (9, 30)
RTH_CLOSE = (16, 0)
OR_MINUTES = 15
OPP_LONG = 0.60
OPP_SHORT = 0.70


def load_trades(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    entries = df[df["type"].str.lower().str.contains("entry")].copy()
    exits = df[df["type"].str.lower().str.contains("exit")].copy()
    entries["datetime"] = pd.to_datetime(entries["date and time"])
    exits["datetime"] = pd.to_datetime(exits["date and time"])
    exit_map = exits.set_index("trade number")[["net pnl usd", "signal", "favorable excursion usd"]]
    exit_map.columns = ["pnl", "exit_signal", "mfe"]
    trades = entries.set_index("trade number").join(exit_map)
    trades = trades.rename(columns={"signal": "direction", "price usd": "entry_px"})
    trades["direction"] = trades["direction"].str.lower()
    trades["win"] = trades["pnl"] > 0
    return trades


def fetch_bars() -> pd.DataFrame:
    df = yf.Ticker("NQ=F").history(period="60d", interval="5m", auto_adjust=False)
    df = df.rename(columns=str.lower)
    df.index = df.index.tz_convert(TZ)
    return df


def is_rth(ts: pd.Timestamp) -> bool:
    if ts.weekday() >= 5:
        return False
    t = ts.time()
    return (t >= dt_time(9, 30)) and (t < dt_time(16, 0))


def compute_vwaps(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    out["hlc3"] = (out["high"] + out["low"] + out["close"]) / 3
    out["vol"] = out["volume"].clip(lower=1)
    out["in_rth"] = [is_rth(ts) for ts in out.index]

    # Session IDs for RTH blocks
    sid = 0
    prev_in = False
    sids = []
    for in_rth in out["in_rth"]:
        if in_rth and not prev_in:
            sid += 1
        sids.append(sid if in_rth else 0)
        prev_in = in_rth
    out["session_id"] = sids

    session_start: dict[int, pd.Timestamp] = {}
    for ts, row in out[out["session_id"] > 0].iterrows():
        s = int(row["session_id"])
        if s not in session_start:
            session_start[s] = ts

    sess_vwap = []
    pd_vwap = []
    sess_pv = 0.0
    sess_v = 0.0
    cur_sess = 0
    pd_pv = 0.0
    pd_v = 0.0
    pd_anchor_sess = 0

    for ts, row in out.iterrows():
        s = int(row["session_id"])
        if s == 0:
            sess_vwap.append(float("nan"))
            pd_vwap.append(float("nan"))
            continue

        if s != cur_sess:
            cur_sess = s
            sess_pv = row["hlc3"] * row["vol"]
            sess_v = row["vol"]
            if s > 1 and (s - 1) in session_start:
                pd_anchor_sess = s - 1
                anchor = session_start[pd_anchor_sess]
                pd_pv = 0.0
                pd_v = 0.0
                seg = out[(out.index >= anchor) & (out.index <= ts)]
                for _, r in seg.iterrows():
                    if r["session_id"] > 0:
                        pd_pv += r["hlc3"] * r["vol"]
                        pd_v += r["vol"]
            else:
                pd_pv = row["hlc3"] * row["vol"]
                pd_v = row["vol"]
        else:
            sess_pv += row["hlc3"] * row["vol"]
            sess_v += row["vol"]
            pd_pv += row["hlc3"] * row["vol"]
            pd_v += row["vol"]

        sess_vwap.append(sess_pv / sess_v)
        pd_vwap.append(pd_pv / pd_v if pd_v > 0 else float("nan"))

    out["session_vwap"] = sess_vwap
    out["prior_day_vwap"] = pd_vwap
    return out


def candle_stats(o, h, l, c) -> dict:
    rng = h - l
    body = abs(c - o)
    body_pct = body / rng if rng > 0 else 0
    close_pos = (c - l) / rng if rng > 0 else 0.5
    return {
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "range": rng,
        "body_pct": body_pct,
        "bullish": c > o,
        "bearish": c < o,
        "close_pos": close_pos,
    }


TZ_CT = "America/Chicago"


def match_bar(bars: pd.DataFrame, dt: pd.Timestamp, entry_px: float) -> tuple[pd.Timestamp | None, str]:
    best = None
    best_diff = float("inf")
    best_tz = ""
    for tz_label, tz in [("ET", TZ), ("CT", TZ_CT)]:
        t = dt.tz_localize(tz) if dt.tzinfo is None else dt.tz_convert(tz)
        t = t.tz_convert(TZ)
        day_bars = bars[bars.index.date == t.date()]
        if day_bars.empty:
            continue
        candidates = day_bars[(day_bars.index.hour == t.hour) & (day_bars.index.minute == t.minute)]
        if candidates.empty:
            idx = (day_bars.index - t).abs().argsort()[:5]
            candidates = day_bars.iloc[idx]
        for ts, row in candidates.iterrows():
            diff = abs(row["close"] - entry_px)
            if diff < best_diff:
                best_diff = diff
                best = ts
                best_tz = tz_label
    if best is not None and best_diff < 25:
        return best, best_tz
    return None, ""


def analyze_loser(idx, trade, bars: pd.DataFrame) -> dict:
    dt = trade["datetime"]
    entry_px = trade["entry_px"]
    direction = trade["direction"]
    bar_ts, tz_used = match_bar(bars, dt, entry_px)
    if bar_ts is None:
        return {"trade": idx, "error": "no bar match"}

    loc = bars.index.get_loc(bar_ts)
    row = bars.iloc[loc]
    prev = bars.iloc[loc - 1] if loc > 0 else None

    e = candle_stats(row["open"], row["high"], row["low"], row["close"])
    p = candle_stats(prev["open"], prev["high"], prev["low"], prev["close"]) if prev is not None else {}

    sv = row["session_vwap"]
    pv = row["prior_day_vwap"]
    vwap_spread = sv - pv if pd.notna(sv) and pd.notna(pv) else float("nan")

    # crosses on entry bar
    prev_row = bars.iloc[loc - 1] if loc > 0 else row
    cross_sess = pd.notna(sv) and row["close"] > sv and prev_row["close"] <= prev_row["session_vwap"] if direction == "long" else (
        pd.notna(sv) and row["close"] < sv and prev_row["close"] >= prev_row["session_vwap"]
    )
    cross_pd = pd.notna(pv) and row["close"] > pv and prev_row["close"] <= prev_row["prior_day_vwap"] if direction == "long" else (
        pd.notna(pv) and row["close"] < pv and prev_row["close"] >= prev_row["prior_day_vwap"]
    )

    above_both = pd.notna(sv) and pd.notna(pv) and row["close"] > sv and row["close"] > pv
    below_both = pd.notna(sv) and pd.notna(pv) and row["close"] < sv and row["close"] < pv

    # opposite filter
    opp_blocked = False
    if p:
        if direction == "long" and p["bearish"] and p["body_pct"] >= OPP_LONG:
            opp_blocked = True
        if direction == "short" and p["bullish"] and p["body_pct"] >= OPP_SHORT:
            opp_blocked = True

    # OR timing (RTH open 9:30 ET)
    sess_open = bar_ts.replace(hour=9, minute=30, second=0, microsecond=0)
    if bar_ts.tzinfo:
        sess_open = sess_open.tz_convert(TZ) if sess_open.tzinfo else sess_open.tz_localize(TZ)
    mins_from_open = (bar_ts - sess_open).total_seconds() / 60

    # entry candle aligned with direction?
    aligned = (direction == "long" and e["bullish"]) or (direction == "short" and e["bearish"])

    # stop estimate from pine: long stop = low - 2 ticks (~0.5 pts MNQ)
    tick = 0.25
    stop_buf = 2 * tick
    if direction == "long":
        stop_px = row["low"] - stop_buf
        risk = entry_px - stop_px
    else:
        stop_px = row["high"] + stop_buf
        risk = stop_px - entry_px

    # forward bars until session end same day
    fwd = bars.loc[bar_ts:].head(80)
    fwd = fwd[fwd.index.date == bar_ts.date()]
    hit_half = hit_one = hit_two = False
    if risk > 0:
        for _, r in fwd.iterrows():
            if direction == "long":
                if r["high"] >= entry_px + 0.5 * risk:
                    hit_half = True
                if r["high"] >= entry_px + risk:
                    hit_one = True
                if r["high"] >= entry_px + 2 * risk:
                    hit_two = True
            else:
                if r["low"] <= entry_px - 0.5 * risk:
                    hit_half = True
                if r["low"] <= entry_px - risk:
                    hit_one = True
                if r["low"] <= entry_px - 2 * risk:
                    hit_two = True

    return {
        "trade": idx,
        "csv_tz": tz_used,
        "datetime": str(dt),
        "direction": direction,
        "pnl": trade["pnl"],
        "mfe_csv": trade["mfe"],
        "bar_ts": str(bar_ts),
        "entry_px": entry_px,
        "bar_close": row["close"],
        "session_vwap": round(sv, 2) if pd.notna(sv) else None,
        "prior_vwap": round(pv, 2) if pd.notna(pv) else None,
        "dist_sess": round(row["close"] - sv, 2) if pd.notna(sv) else None,
        "dist_prior": round(row["close"] - pv, 2) if pd.notna(pv) else None,
        "vwap_spread": round(vwap_spread, 2) if pd.notna(vwap_spread) else None,
        "cross_sess": cross_sess,
        "cross_pd": cross_pd,
        "position_ok": above_both if direction == "long" else below_both,
        "mins_from_open": round(mins_from_open, 0),
        "after_or": mins_from_open > OR_MINUTES,
        "entry_bullish": e["bullish"],
        "entry_body_pct": round(e["body_pct"], 2),
        "entry_close_pos": round(e["close_pos"], 2),
        "entry_aligned": aligned,
        "prior_bullish": p.get("bullish"),
        "prior_body_pct": round(p.get("body_pct", 0), 2),
        "opp_would_block": opp_blocked,
        "risk_pts": round(risk, 2),
        "hit_0_5r": hit_half,
        "hit_1r": hit_one,
        "hit_2r": hit_two,
        "entry_range": round(e["range"], 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", nargs="?", default="/Users/daniel/Downloads/Session_Levels_CME_MINI_MNQ1!_2026-06-25 (2).csv")
    args = parser.parse_args()

    trades = load_trades(Path(args.csv))
    losers = trades[~trades["win"]].sort_values("pnl")
    print(f"Loading NQ 5m bars...")
    bars = fetch_bars()
    print(f"Computing VWAPs...")
    bars = compute_vwaps(bars)

    results = []
    for idx, trade in losers.iterrows():
        results.append(analyze_loser(idx, trade, bars))

    df = pd.DataFrame(results)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print("\n" + "=" * 80)
    print("LOSING TRADE CANDLE + VWAP ANALYSIS")
    print("=" * 80)
    for r in results:
        if "error" in r:
            print(f"\n#{r['trade']}: {r['error']}")
            continue
        print(f"\n--- Trade #{r['trade']} {r['datetime']} {r['direction'].upper()} ${r['pnl']:,.0f} ---")
        print(f"  Entry bar: O/H/L/C → bullish={r['entry_bullish']} body={r['entry_body_pct']:.0%} close_pos={r['entry_close_pos']:.0%} aligned={r['entry_aligned']}")
        print(f"  Prior bar: bullish={r['prior_bullish']} body={r['prior_body_pct']:.0%} opp_filter_would_block={r['opp_would_block']}")
        print(f"  VWAP: sess={r['session_vwap']} prior={r['prior_vwap']} spread={r['vwap_spread']} dist_sess={r['dist_sess']} dist_prior={r['dist_prior']}")
        print(f"  Cross: session={r['cross_sess']} prior_day={r['cross_pd']} | {r['mins_from_open']:.0f}min from open, after_OR={r['after_or']}")
        print(f"  Risk={r['risk_pts']}pts | hit 0.5R={r['hit_0_5r']} 1R={r['hit_1r']} 2R={r['hit_2r']} | MFE(csv)=${r['mfe_csv']:,.0f}")

    # aggregate patterns
    ok = [r for r in results if "error" not in r]
    print("\n" + "=" * 80)
    print("PATTERN SUMMARY")
    print("=" * 80)
    n = len(ok)
    print(f"Entry candle NOT aligned with direction: {sum(1 for r in ok if not r['entry_aligned'])}/{n}")
    print(f"Prior opposite filter WOULD have blocked: {sum(1 for r in ok if r['opp_would_block'])}/{n}")
    print(f"Cross session VWAP only (not prior): {sum(1 for r in ok if r['cross_sess'] and not r['cross_pd'])}/{n}")
    print(f"Cross prior VWAP only (not session): {sum(1 for r in ok if r['cross_pd'] and not r['cross_sess'])}/{n}")
    print(f"Entry body < 50%: {sum(1 for r in ok if r['entry_body_pct'] < 0.5)}/{n}")
    print(f"Within 15min of open (OR period): {sum(1 for r in ok if not r['after_or'])}/{n}")
    print(f"Hit 1R before stop: {sum(1 for r in ok if r['hit_1r'])}/{n}")
    print(f"Hit 2R before stop: {sum(1 for r in ok if r['hit_2r'])}/{n}")
    print(f"Never hit 0.5R: {sum(1 for r in ok if not r['hit_0_5r'])}/{n}")
    avg_dist = sum(abs(r['dist_sess'] or 0) for r in ok) / n
    print(f"Avg |distance from session VWAP| at entry: {avg_dist:.1f} pts")

    out = Path("output/loser_candle_analysis.csv")
    out.parent.mkdir(exist_ok=True)
    pd.DataFrame(ok).to_csv(out, index=False)
    print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
