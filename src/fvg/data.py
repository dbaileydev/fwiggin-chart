from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf


REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [str(col[0]).lower() for col in df.columns]

    rename_map = {
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename_map)
    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    out = df.loc[:, list(REQUIRED_COLUMNS)].copy()
    out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_convert("UTC").tz_localize(None)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out.dropna()


def fetch_yfinance(
    symbol: str,
    *,
    interval: str = "5m",
    period: str = "60d",
) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval, auto_adjust=False)
    if df.empty:
        raise RuntimeError(
            f"No data returned for {symbol} ({interval}, {period}). "
            "Try a shorter interval window or load a CSV."
        )
    return normalize_ohlcv(df)


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    ts_col = None
    for candidate in ("datetime", "timestamp", "date", "time"):
        if candidate in df.columns:
            ts_col = candidate
            break
    if ts_col is None:
        raise ValueError("CSV must include a datetime/timestamp/date/time column")
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df.set_index(ts_col)
    return normalize_ohlcv(df)
