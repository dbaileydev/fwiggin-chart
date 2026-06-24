# MNQ Fair Value Gap Backtest

Backtest an ICT-style fair value gap (FVG) strategy on Micro E-mini Nasdaq futures (MNQ).

Price data uses the continuous Nasdaq futures symbol `NQ=F` (same index points as MNQ). PnL is modeled with MNQ contract specs ($2/point).

## Strategy

1. **Detect FVGs** using the 3-candle imbalance rule:
   - Bullish: `low[i] > high[i-2]`
   - Bearish: `high[i] < low[i-2]`
2. **Filter** by minimum gap size, optional EMA trend, and optional RTH session.
3. **Enter** when price retraces into the gap:
   - `ce` — 50% consequent encroachment (default)
   - `edge` — top (bull) / bottom (bear)
   - `full` — full fill into the gap
4. **Stop** beyond the gap with a tick buffer.
5. **Target** at a fixed risk:reward (default 2R).
6. **Risk** sizes positions at 1% of equity per trade (configurable).

## Setup

```bash
cd ~/Projects/trading/mnq-fvg-backtest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python run_backtest.py
```

Use your own CSV (must include `datetime` + OHLCV columns):

```bash
python run_backtest.py --csv data/mnq_5m.csv --save-trades output/trades.csv
```

## Config

Edit `config/default.yaml` to tune:

- `interval` / `period` — yfinance window (`5m` + `60d` is the max intraday range)
- `fvg.min_gap_points` — ignore small imbalances (default **8**)
- `strategy.min_stop_points` — skip tight stops (default **20**)
- `strategy.displacement` — require impulsive middle candle
- `strategy.require_trend_at_entry` — EMA must align when price tags entry
- `strategy.entry_mode` — `ce`, `edge`, or `full`
- `strategy.risk_reward` — take-profit multiple
- `strategy.require_trend` — only trade with EMA bias at FVG formation
- `backtest.risk_per_trade_pct` — position sizing

## TradingView indicators

### 15m FVG only (`tradingview/FVG_15m.pine`)
Marks **15-minute** fair value gaps on any chart timeframe (1m, 5m, etc.):
- Light green / red transparent boxes
- Black dashed **50% CE** midline
- Boxes extend right until mitigated

Paste into Pine Editor → Add to chart on MNQ1!.

### Entry signals (`tradingview/MNQ_FVG_Entry_Signals.pine`)
Full strategy overlay with entry arrows, stops, and targets.

1. Open TradingView → Pine Editor → New blank indicator
2. Paste the file contents → Save → Add to chart
3. Use **MNQ1!** or **NQ1!** on your preferred timeframe (5m matches the backtest default)

The indicator draws FVG boxes, plots EMA trend filter, and marks **LONG** / **SHORT** arrows when price retraces to the entry level (CE by default). Labels include entry, stop, and target prices. Enable alerts on "FVG Long Entry" / "FVG Short Entry".

## Notes

- yfinance intraday history is limited (5m ≈ 60 days). For longer or tick-level backtests, export data from your broker or data vendor and pass `--csv`.
- This is a research scaffold, not live trading advice. Validate on out-of-sample data before risking capital.
