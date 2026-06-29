#!/usr/bin/env python3
"""Analyze TradingView trade list exports for defensive-mode parameter tuning."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import product
from pathlib import Path

import pandas as pd


@dataclass
class RoundTrip:
    trade_num: int
    entry_time: pd.Timestamp
    session_date: object
    month: pd.Period
    side: str
    qty: int
    pnl: float
    exit_signals: str
    max_favorable: float
    max_adverse: float
    duration_bars: int

    @property
    def is_win(self) -> bool:
        return self.pnl > 0

    @property
    def is_loss(self) -> bool:
        return self.pnl < 0

    @property
    def is_stop(self) -> bool:
        return "Stop Loss" in self.exit_signals


def load_round_trips(path: Path) -> list[RoundTrip]:
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    df["dt"] = pd.to_datetime(df["Date and time"])

    trips: list[RoundTrip] = []
    for trade_num, grp in df.groupby("Trade number"):
        grp = grp.sort_values("dt")
        entry = grp[grp["Type"].str.startswith("Entry", na=False)]
        exits = grp[grp["Type"].str.startswith("Exit", na=False)]
        if entry.empty or exits.empty:
            continue
        e = entry.iloc[0]
        pnl = float(exits["Net PnL USD"].sum())
        trips.append(
            RoundTrip(
                trade_num=int(trade_num),
                entry_time=pd.Timestamp(e["dt"]),
                session_date=pd.Timestamp(e["dt"]).date(),
                month=pd.Timestamp(e["dt"]).to_period("M"),
                side=str(e["Signal"]),
                qty=int(e["Size (qty)"]),
                pnl=pnl,
                exit_signals=" | ".join(exits["Signal"].astype(str).tolist()),
                max_favorable=float(exits["Favorable excursion USD"].max()),
                max_adverse=float(exits["Adverse excursion USD"].max()),
                duration_bars=int(exits["Duration (bars)"].max()),
            )
        )
    trips.sort(key=lambda t: t.entry_time)
    return trips


def daily_pnl(trips: list[RoundTrip]) -> pd.Series:
    s = pd.Series({t.session_date: 0.0 for t in trips})
    for t in trips:
        s[t.session_date] += t.pnl
    return s.sort_index()


@dataclass
class DefensiveState:
    active: bool = False
    consec_loss_days: int = 0
    consec_win_days: int = 0
    consec_loss_trades: int = 0
    consec_win_trades: int = 0


def simulate_day_based(
    trips: list[RoundTrip],
    loss_days: int,
    win_days: int,
) -> tuple[list[bool], DefensiveState]:
    """Return defensive-active flag per trade (evaluated at entry)."""
    day_pnl = daily_pnl(trips)
    traded_days = sorted({t.session_date for t in trips})
    day_defensive: dict[object, bool] = {}
    st = DefensiveState()

    for d in traded_days:
        # Defensive at start of session day (after prior day's update)
        day_defensive[d] = st.active
        pnl = float(day_pnl.get(d, 0.0))
        if pnl < 0:
            st.consec_loss_days += 1
            st.consec_win_days = 0
            if st.consec_loss_days >= loss_days:
                st.active = True
        elif pnl > 0:
            st.consec_win_days += 1
            st.consec_loss_days = 0
            if st.active and st.consec_win_days >= win_days:
                st.active = False
        else:
            st.consec_loss_days = 0
            st.consec_win_days = 0

    flags = [day_defensive[t.session_date] for t in trips]
    return flags, st


def simulate_trade_based(
    trips: list[RoundTrip],
    loss_trades: int,
    win_trades: int,
) -> tuple[list[bool], DefensiveState]:
    st = DefensiveState()
    flags: list[bool] = []
    for t in trips:
        flags.append(st.active)
        if t.is_loss:
            st.consec_loss_trades += 1
            st.consec_win_trades = 0
            if st.consec_loss_trades >= loss_trades:
                st.active = True
        elif t.is_win:
            st.consec_win_trades += 1
            st.consec_loss_trades = 0
            if st.active and st.consec_win_trades >= win_trades:
                st.active = False
        else:
            st.consec_loss_trades = 0
            st.consec_win_trades = 0
    return flags, st


def estimate_defensive_pnl(
    t: RoundTrip,
    *,
    normal_partial_rr: float = 2.0,
    def_partial_rr: float = 1.0,
    def_trail_rr: float = 1.0,
    partial_pct: float = 0.5,
) -> float:
    """Rough counterfactual PnL when defensive R:R applies (same size)."""
    risk = abs(t.max_adverse)
    if risk <= 0:
        return t.pnl

    fav = t.max_favorable
    qty_scale = t.qty / 6.0
    runner_frac = 1.0 - partial_pct

    # Full stop before any partial level
    if t.is_stop and fav < risk * def_partial_rr:
        return t.pnl

    partial_pnl = risk * def_partial_rr * partial_pct * qty_scale

    # Stop after partial but before trail — assume partial saved + smaller runner loss
    if t.is_stop and fav >= risk * def_partial_rr:
        runner_loss = min(risk * runner_frac * qty_scale, abs(t.pnl - partial_pnl))
        return partial_pnl - runner_loss

    # Winner: if never reached normal 2R but reached defensive 1R
    if fav >= risk * def_partial_rr and fav < risk * normal_partial_rr:
        runner_gain = max(0.0, fav - risk * def_trail_rr) * runner_frac * qty_scale * 0.35
        return partial_pnl + runner_gain

    # Big winner that hit 2R+ — defensive takes less but still positive
    if fav >= risk * normal_partial_rr:
        return t.pnl * (def_partial_rr / normal_partial_rr) * 0.85 + t.pnl * 0.15

    return t.pnl


def score_period(
    trips: list[RoundTrip],
    flags: list[bool],
    *,
    def_partial_rr: float = 1.0,
    def_trail_rr: float = 1.0,
) -> dict:
    baseline = sum(t.pnl for t in trips)
    def_trips = [t for t, f in zip(trips, flags) if f]
    normal_trips = [t for t, f in zip(trips, flags) if not f]

    skip_def_pnl = sum(t.pnl for t in normal_trips)
    modified_pnl = sum(
        estimate_defensive_pnl(t, def_partial_rr=def_partial_rr, def_trail_rr=def_trail_rr)
        if f
        else t.pnl
        for t, f in zip(trips, flags)
    )

    def_pnl_actual = sum(t.pnl for t in def_trips)
    def_stops = sum(1 for t in def_trips if t.is_stop)
    def_wins = sum(1 for t in def_trips if t.is_win)

    return {
        "baseline_pnl": baseline,
        "skip_defensive_pnl": skip_def_pnl,
        "modified_defensive_pnl": modified_pnl,
        "delta_skip": skip_def_pnl - baseline,
        "delta_modified": modified_pnl - baseline,
        "defensive_trade_count": len(def_trips),
        "defensive_pct": len(def_trips) / len(trips) if trips else 0,
        "defensive_pnl_actual": def_pnl_actual,
        "defensive_stops": def_stops,
        "defensive_wins": def_wins,
    }


def q1_mask(trips: list[RoundTrip], year: int) -> list[bool]:
    return [t.entry_time.year == year and t.entry_time.month <= 3 for t in trips]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--out", type=Path, default=Path("output/defensive_analysis"))
    args = parser.parse_args()

    trips = load_round_trips(args.csv_path)
    args.out.mkdir(parents=True, exist_ok=True)

    baseline_total = sum(t.pnl for t in trips)
    print(f"Loaded {len(trips)} round-trip trades from {trips[0].entry_time.date()} to {trips[-1].entry_time.date()}")
    print(f"Baseline total PnL: ${baseline_total:,.0f}\n")

    # Monthly breakdown
    monthly = pd.DataFrame(
        [{"month": str(t.month), "pnl": t.pnl, "win": t.is_win} for t in trips]
    ).groupby("month").agg(trades=("pnl", "count"), pnl=("pnl", "sum"), wins=("win", "sum"))
    monthly["win_rate"] = (monthly["wins"] / monthly["trades"] * 100).round(1)
    monthly.to_csv(args.out / "monthly_pnl.csv")
    print("=== Monthly PnL ===")
    print(monthly.to_string())
    print()

    for year in sorted({t.entry_time.year for t in trips}):
        q1_trips = [t for t, m in zip(trips, q1_mask(trips, year)) if m]
        if not q1_trips:
            continue
        q1_pnl = sum(t.pnl for t in q1_trips)
        q1_stops = sum(1 for t in q1_trips if t.is_stop)
        print(
            f"Q1 {year}: {len(q1_trips)} trades, PnL ${q1_pnl:,.0f}, "
            f"stops {q1_stops} ({q1_stops/len(q1_trips)*100:.0f}%), "
            f"win rate {sum(t.is_win for t in q1_trips)/len(q1_trips)*100:.0f}%"
        )
    print()

    day_grid: list[dict] = []
    for loss_d, win_d in product([1, 2, 3, 4], [1, 2, 3]):
        flags, _ = simulate_day_based(trips, loss_d, win_d)
        s = score_period(trips, flags)
        q1_26 = [t for t, f, m in zip(trips, flags, q1_mask(trips, 2026)) if m]
        q1_26_flags = [f for f, m in zip(flags, q1_mask(trips, 2026)) if m]
        q1_26_def = sum(1 for f in q1_26_flags if f)
        day_grid.append(
            {
                "mode": "days",
                "loss_to_activate": loss_d,
                "win_to_deactivate": win_d,
                **s,
                "q1_2026_trades": len(q1_26),
                "q1_2026_defensive_trades": q1_26_def,
                "q1_2026_defensive_pct": q1_26_def / len(q1_26) if q1_26 else 0,
            }
        )

    trade_grid: list[dict] = []
    for loss_t, win_t in product([2, 3, 4, 5], [1, 2, 3]):
        flags, _ = simulate_trade_based(trips, loss_t, win_t)
        s = score_period(trips, flags)
        q1_26_flags = [f for f, m in zip(flags, q1_mask(trips, 2026)) if m]
        q1_26_def = sum(1 for f in q1_26_flags if f)
        trade_grid.append(
            {
                "mode": "trades",
                "loss_to_activate": loss_t,
                "win_to_deactivate": win_t,
                **s,
                "q1_2026_defensive_pct": q1_26_def / sum(q1_mask(trips, 2026)) if any(q1_mask(trips, 2026)) else 0,
            }
        )

    day_df = pd.DataFrame(day_grid).sort_values("modified_defensive_pnl", ascending=False)
    trade_df = pd.DataFrame(trade_grid).sort_values("modified_defensive_pnl", ascending=False)
    day_df.to_csv(args.out / "grid_day_based.csv", index=False)
    trade_df.to_csv(args.out / "grid_trade_based.csv", index=False)

    print("=== Top 5 day-based configs (by estimated modified PnL) ===")
    cols = [
        "loss_to_activate",
        "win_to_deactivate",
        "baseline_pnl",
        "modified_defensive_pnl",
        "delta_modified",
        "skip_defensive_pnl",
        "delta_skip",
        "defensive_pct",
        "q1_2026_defensive_pct",
    ]
    print(day_df[cols].head(5).to_string(index=False))
    print()

    print("=== Top 5 trade-based configs (by estimated modified PnL) ===")
    print(trade_df[cols].head(5).to_string(index=False))
    print()

    # Defensive R:R sensitivity on best day config
    best_day = day_df.iloc[0]
    flags, _ = simulate_day_based(
        trips, int(best_day["loss_to_activate"]), int(best_day["win_to_deactivate"])
    )
    rr_rows = []
    for p_rr, t_rr in product([0.75, 1.0, 1.5, 2.0], [1.0, 1.5, 2.0]):
        s = score_period(trips, flags, def_partial_rr=p_rr, def_trail_rr=t_rr)
        rr_rows.append({"def_partial_rr": p_rr, "def_trail_rr": t_rr, **s})
    rr_df = pd.DataFrame(rr_rows).sort_values("modified_defensive_pnl", ascending=False)
    rr_df.to_csv(args.out / "grid_defensive_rr_best_day.csv", index=False)
    print(
        f"=== Defensive R:R sweep (day config: {int(best_day['loss_to_activate'])} loss days / "
        f"{int(best_day['win_to_deactivate'])} win days) ==="
    )
    print(rr_df[["def_partial_rr", "def_trail_rr", "modified_defensive_pnl", "delta_modified"]].head(6).to_string(index=False))
    print()

    # Timeline: when defensive would be on during Q1 2026
    flags_day, _ = simulate_day_based(trips, 3, 2)
    print("=== Q1 2026 trades — day-based defensive (3 loss days / 2 win days) ===")
    for t, f in zip(trips, flags_day):
        if t.entry_time.year == 2026 and t.entry_time.month <= 3:
            print(
                f"{t.entry_time.date()} {t.side:5} ${t.pnl:8,.0f}  "
                f"{'DEFENSIVE' if f else 'normal':9}  {t.exit_signals[:40]}"
            )

    flags_trade, _ = simulate_trade_based(trips, 3, 2)
    print("\n=== Q1 2026 — trade-based defensive (3 loss trades / 2 win trades) ===")
    for t, f in zip(trips, flags_trade):
        if t.entry_time.year == 2026 and t.entry_time.month <= 3:
            print(
                f"{t.entry_time.date()} {t.side:5} ${t.pnl:8,.0f}  "
                f"{'DEFENSIVE' if f else 'normal':9}  {t.exit_signals[:40]}"
            )

    print(f"\nWrote CSVs to {args.out}")


if __name__ == "__main__":
    main()
