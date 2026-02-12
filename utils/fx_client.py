from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

import yfinance as yf


def fetch_fx_latest_and_prev(ticker: str) -> Tuple[Tuple[str, float], Tuple[str, float]]:
    """
    Fetch latest and previous daily close for a FX ticker via yfinance.
    Returns: ((date, close), (date, close))
    """
    # 10 days is enough to survive weekends/holidays
    df = yf.download(ticker, period="10d", interval="1d", auto_adjust=False, progress=False)

    if df is None or df.empty:
        raise RuntimeError(f"No data returned for ticker: {ticker}")

    closes = df["Close"].dropna()
    if len(closes) < 2:
        raise RuntimeError(f"Not enough daily closes for ticker: {ticker}")

    latest_dt = closes.index[-1].to_pydatetime()
    prev_dt = closes.index[-2].to_pydatetime()

    latest_raw = closes.iloc[-1]
    prev_raw = closes.iloc[-2]

    # Some yfinance outputs can make these rows Series instead of scalars.
    latest_px = float(latest_raw.iloc[0]) if hasattr(latest_raw, "iloc") else float(latest_raw)
    prev_px = float(prev_raw.iloc[0]) if hasattr(prev_raw, "iloc") else float(prev_raw)

    latest = (latest_dt.strftime("%Y-%m-%d"), latest_px)
    prev = (prev_dt.strftime("%Y-%m-%d"), prev_px)

    return latest, prev


def pct_change(latest: float, prev: float) -> float:
    """
    Daily % change (e.g. +0.45 means +0.45%)
    """
    if prev == 0:
        return 0.0
    return (latest / prev - 1.0) * 100.0
