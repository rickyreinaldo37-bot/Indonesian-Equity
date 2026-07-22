"""Net foreign flow analytics.

The stylised fact this module quantifies: IDX blue chips — the big four
banks above all — move with foreign money. Daily net foreign flow (net
foreign buy value, IDR bn) comes from the flow cache (see src/fetch.py for
the source hierarchy); here we compute the horizon sums, cumulative series,
and flow/return correlations used by comps, charts, and reports.

Pure computation lives in functions that take pandas objects (unit-tested
with hand fixtures); thin wrappers read the cache.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

from src import fetch

HORIZONS: list[tuple[str, int]] = [
    ("1W", 7), ("1M", 30), ("3M", 91), ("6M", 182), ("12M", 365),
]


# ---------------------------------------------------------------------------
# Pure functions (unit-tested)
# ---------------------------------------------------------------------------

def window_sum(flow: pd.Series, days: int,
               end: pd.Timestamp | None = None) -> float:
    """Sum of flow over the trailing `days` calendar days ending at `end`
    (inclusive; default = last observation)."""
    if flow.empty:
        return float("nan")
    end = end or flow.index[-1]
    start = end - pd.Timedelta(days=days)
    return float(flow[(flow.index > start) & (flow.index <= end)].sum())


def ytd_sum(flow: pd.Series, end: pd.Timestamp | None = None) -> float:
    if flow.empty:
        return float("nan")
    end = end or flow.index[-1]
    start = pd.Timestamp(dt.date(end.year, 1, 1))
    return float(flow[(flow.index >= start) & (flow.index <= end)].sum())


def horizon_table(flow: pd.Series) -> pd.Series:
    """Net flow sums (same unit as input) for the standard horizons + YTD."""
    out = {label: window_sum(flow, days) for label, days in HORIZONS}
    out["YTD"] = ytd_sum(flow)
    return pd.Series(out)


def cumulative(flow: pd.Series, start: pd.Timestamp | None = None) -> pd.Series:
    """Cumulative net flow from `start` (default: full series), starting at 0."""
    if start is not None:
        flow = flow[flow.index >= start]
    return flow.cumsum()


def flow_return_correlation(flow: pd.Series, close: pd.Series,
                            years: float = 1.0,
                            freq: str = "D") -> float:
    """Pearson correlation between net flow and price returns over the
    trailing `years`, on daily ("D") or weekly ("W", Fri-anchored) frequency.
    Dates are inner-joined; NaNs dropped. Contemporaneous — a diagnostic of
    co-movement, not a predictive claim."""
    end = min(flow.index[-1], close.index[-1])
    start = end - pd.Timedelta(days=int(365 * years))
    flow = flow[(flow.index > start) & (flow.index <= end)]
    close = close[(close.index > start - pd.Timedelta(days=14))
                  & (close.index <= end)]
    if freq == "W":
        flow = flow.resample("W-FRI").sum()
        close = close.resample("W-FRI").last()
    ret = close.pct_change()
    joined = pd.concat([flow.rename("flow"), ret.rename("ret")],
                       axis=1, join="inner").dropna()
    if len(joined) < 8:
        return float("nan")
    return float(joined["flow"].corr(joined["ret"]))


# ---------------------------------------------------------------------------
# Cache-backed wrappers
# ---------------------------------------------------------------------------

def flow_series(ticker: str) -> pd.Series:
    """Daily net foreign flow in IDR bn."""
    return fetch.load_foreign_flow(ticker)["net_foreign_idr_bn"]


def bank_flow_summary(ticker: str) -> dict:
    """Everything comps/reports need for one bank. Sums in IDR tn."""
    flow = flow_series(ticker)
    close = fetch.load_prices(ticker)["Close"].dropna()
    horizons_tn = horizon_table(flow) / 1000.0
    return {
        "horizons_tn": horizons_tn,
        "flow_3m_tn": float(horizons_tn["3M"]),
        "flow_12m_tn": float(horizons_tn["12M"]),
        "corr_daily_1y": flow_return_correlation(flow, close, 1.0, "D"),
        "corr_weekly_1y": flow_return_correlation(flow, close, 1.0, "W"),
        "last_date": flow.index[-1].date(),
    }
