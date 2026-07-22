"""F1 — Data layer.

Live pulls come from yfinance and are cached locally (parquet for prices,
JSON for normalized fundamentals) so every downstream module reads from the
cache and never touches the network. When the network is unavailable the
cache is served as-is; every cache file carries a `source` tag so outputs
can disclose whether they were built from live or sample data.

Manual bank metrics (NIM, CASA, NPL, CAR, loan growth, cost of credit,
cost/income) are the analyst-maintained source of truth, transcribed from
quarterly investor presentations into data/manual/<TICKER>.csv.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src import config


class ManualDataError(Exception):
    """Raised when a manual input file is missing fields or malformed."""


# ---------------------------------------------------------------------------
# Price data
# ---------------------------------------------------------------------------

def _price_path(ticker: str) -> Path:
    return config.PRICE_CACHE_DIR / f"{ticker}.parquet"


def _meta_path(ticker: str) -> Path:
    return config.PRICE_CACHE_DIR / f"{ticker}.meta.json"


def fetch_prices(tickers: list[str] | None = None,
                 start: str = config.PRICE_START,
                 force: bool = False) -> dict[str, pd.DataFrame]:
    """Fetch daily OHLCV for each ticker via yfinance, caching to parquet.

    Falls back to the existing cache when the network is unreachable.
    Returns {ticker: DataFrame indexed by date}.
    """
    tickers = tickers or config.TICKERS
    out: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        yf_symbol = config.UNIVERSE[ticker]["yf"]
        cached = _read_price_cache(ticker)
        if cached is not None and not force and _is_fresh(ticker):
            out[ticker] = cached
            continue
        fresh = _download_prices(yf_symbol, start)
        if fresh is not None and len(fresh):
            fresh.to_parquet(_price_path(ticker))
            _write_meta(ticker, config.SOURCE_YFINANCE, start)
            out[ticker] = fresh
            print(f"  {ticker}: fetched {len(fresh):,} rows from yfinance")
        elif cached is not None:
            src = price_source(ticker)
            print(f"  {ticker}: network unavailable — serving cache "
                  f"({len(cached):,} rows, source={src})")
            out[ticker] = cached
        else:
            raise RuntimeError(
                f"No price data for {ticker}: yfinance unreachable and no "
                f"local cache. Run scripts/make_sample_seed.py to install "
                f"sample data, or retry with network access.")
    return out


def _download_prices(yf_symbol: str, start: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(yf_symbol, start=start, progress=False,
                         auto_adjust=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Adj Close": "AdjClose"})
        keep = [c for c in ("Open", "High", "Low", "Close", "AdjClose",
                            "Volume") if c in df.columns]
        df = df[keep]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "date"
        return df
    except Exception:
        return None


def _read_price_cache(ticker: str) -> pd.DataFrame | None:
    path = _price_path(ticker)
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df


def _is_fresh(ticker: str) -> bool:
    """True when the cache was fetched from yfinance today (skip re-pull)."""
    meta = read_meta(ticker)
    if meta.get("source") != config.SOURCE_YFINANCE:
        return False
    fetched = meta.get("fetched_at", "")
    return fetched[:10] == dt.date.today().isoformat()


def _write_meta(ticker: str, source: str, start: str) -> None:
    meta = {"source": source, "start": start,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds")}
    _meta_path(ticker).write_text(json.dumps(meta, indent=2))


def read_meta(ticker: str) -> dict:
    path = _meta_path(ticker)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def price_source(ticker: str) -> str:
    return read_meta(ticker).get("source", "unknown")


def load_prices(ticker: str) -> pd.DataFrame:
    """Cache-only reader used by comps/charts/valuation (never networks)."""
    df = _read_price_cache(ticker)
    if df is None:
        raise RuntimeError(
            f"No cached prices for {ticker}. Run `python refresh.py` first.")
    return df


def last_close(ticker: str) -> tuple[float, pd.Timestamp]:
    px = load_prices(ticker)["Close"].dropna()
    return float(px.iloc[-1]), px.index[-1]


# ---------------------------------------------------------------------------
# Fundamentals (normalized schema, cached as JSON)
# ---------------------------------------------------------------------------

def _fund_path(ticker: str) -> Path:
    return config.FUND_CACHE_DIR / f"{ticker}.json"


def fetch_fundamentals(ticker: str, force: bool = False) -> dict:
    """Fetch income statement / balance sheet basics from yfinance and
    normalize into a compact schema:

        {ticker, source, fetched_at, shares_outstanding,
         annual: {"2024": {net_income, total_equity, total_assets,
                            eps, bvps, dps}, ...}}

    Values are IDR (statements) and IDR per share (eps/bvps/dps).
    Falls back to the cached file when the network is unreachable.
    """
    cached = _read_fund_cache(ticker)
    if cached is not None and not force and \
            cached.get("source") == config.SOURCE_YFINANCE and \
            cached.get("fetched_at", "")[:10] == dt.date.today().isoformat():
        return cached
    fresh = _download_fundamentals(ticker)
    if fresh is not None:
        _fund_path(ticker).write_text(json.dumps(fresh, indent=2))
        print(f"  {ticker}: fundamentals refreshed from yfinance "
              f"({len(fresh['annual'])} fiscal years)")
        return fresh
    if cached is not None:
        print(f"  {ticker}: network unavailable — serving cached "
              f"fundamentals (source={cached.get('source')})")
        return cached
    raise RuntimeError(
        f"No fundamentals for {ticker}: yfinance unreachable and no local "
        f"cache. Run scripts/make_sample_seed.py or retry with network.")


def _download_fundamentals(ticker: str) -> dict | None:
    try:
        import yfinance as yf
        t = yf.Ticker(config.UNIVERSE[ticker]["yf"])
        income = t.income_stmt
        balance = t.balance_sheet
        if income is None or income.empty or balance is None or balance.empty:
            return None
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        shares = float(info.get("sharesOutstanding") or 0)
        divs = None
        try:
            divs = t.dividends
        except Exception:
            pass

        annual: dict[str, dict] = {}
        for col in income.columns:
            year = str(pd.Timestamp(col).year)
            ni = _stmt_value(income, col, ["Net Income",
                                          "Net Income Common Stockholders"])
            eq = _stmt_value(balance, col, ["Stockholders Equity",
                                           "Total Equity Gross Minority Interest"])
            ta = _stmt_value(balance, col, ["Total Assets"])
            sh = _stmt_value(balance, col, ["Ordinary Shares Number",
                                           "Share Issued"]) or shares
            if not ni or not eq or not sh:
                continue
            dps = 0.0
            if divs is not None and len(divs):
                dps = float(divs[divs.index.year == int(year)].sum())
            annual[year] = {
                "net_income": ni, "total_equity": eq, "total_assets": ta,
                "shares": sh, "eps": ni / sh, "bvps": eq / sh, "dps": dps,
            }
        if not annual:
            return None
        return {
            "ticker": ticker,
            "source": config.SOURCE_YFINANCE,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "shares_outstanding": shares or max(
                v["shares"] for v in annual.values()),
            "annual": dict(sorted(annual.items())),
        }
    except Exception:
        return None


def _stmt_value(frame: pd.DataFrame, col, names: list[str]) -> float | None:
    for name in names:
        if name in frame.index:
            val = frame.loc[name, col]
            if pd.notna(val):
                return float(val)
    return None


def _read_fund_cache(ticker: str) -> dict | None:
    path = _fund_path(ticker)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_fundamentals(ticker: str) -> dict:
    """Cache-only fundamentals reader for downstream modules."""
    data = _read_fund_cache(ticker)
    if data is None:
        raise RuntimeError(
            f"No cached fundamentals for {ticker}. Run `python refresh.py`.")
    return data


def fundamentals_frame(ticker: str) -> pd.DataFrame:
    """Annual fundamentals as a DataFrame indexed by fiscal year (int)."""
    data = load_fundamentals(ticker)
    df = pd.DataFrame(data["annual"]).T
    df.index = df.index.astype(int)
    return df.sort_index()


# ---------------------------------------------------------------------------
# Analyst consensus (target price, ratings, consensus forward EPS)
# ---------------------------------------------------------------------------
# Yahoo Finance aggregates sell-side analyst targets and estimates for these
# liquid names. We treat it as a convenience source, cached and source-tagged
# like everything else; an analyst-sourced override in assumptions/<TICKER>.yaml
# (consensus block) takes priority when set. IMPORTANT: consensus figures are
# never fabricated — when no live/manual source is available the value is
# reported as n/a, and any SAMPLE placeholder is loudly tagged.

CONSENSUS_FIELDS = [
    "target_mean", "target_high", "target_low", "num_analysts",
    "recommendation_key", "recommendation_mean", "consensus_forward_eps",
]


def _consensus_path(ticker: str) -> Path:
    return config.CONSENSUS_CACHE_DIR / f"{ticker}.json"


def fetch_consensus(ticker: str, force: bool = False) -> dict:
    """Refresh analyst consensus from yfinance, cached to JSON. Falls back to
    cache when the network is unavailable; raises if neither exists."""
    cached = _read_consensus_cache(ticker)
    if cached is not None and not force and \
            cached.get("source") == config.SOURCE_YFINANCE and \
            cached.get("fetched_at", "")[:10] == dt.date.today().isoformat():
        return cached
    fresh = _download_consensus(ticker)
    if fresh is not None:
        _consensus_path(ticker).write_text(json.dumps(fresh, indent=2))
        n = fresh.get("num_analysts")
        print(f"  {ticker}: consensus refreshed from yfinance "
              f"(target {fresh.get('target_mean')}, "
              f"{n if n else '?'} analysts)")
        return fresh
    if cached is not None:
        print(f"  {ticker}: network unavailable — serving cached consensus "
              f"(source={cached.get('source')})")
        return cached
    raise RuntimeError(
        f"No consensus for {ticker}: yfinance unreachable and no local cache. "
        f"Run scripts/make_sample_seed.py or set the consensus block in "
        f"assumptions/{ticker}.yaml.")


def _download_consensus(ticker: str) -> dict | None:
    try:
        import yfinance as yf
        info = yf.Ticker(config.UNIVERSE[ticker]["yf"]).info or {}
    except Exception:
        return None
    if not info:
        return None
    target = info.get("targetMeanPrice")
    if target is None:
        return None  # no analyst coverage returned

    def _num(key):
        v = info.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    payload = {
        "ticker": ticker,
        "source": config.SOURCE_YFINANCE,
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "target_mean": _num("targetMeanPrice"),
        "target_high": _num("targetHighPrice"),
        "target_low": _num("targetLowPrice"),
        "num_analysts": _num("numberOfAnalystOpinions"),
        "recommendation_key": info.get("recommendationKey"),
        "recommendation_mean": _num("recommendationMean"),
        "consensus_forward_eps": _num("forwardEps"),
    }
    return payload


def _read_consensus_cache(ticker: str) -> dict | None:
    path = _consensus_path(ticker)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_consensus(ticker: str) -> dict | None:
    """Cache-only consensus reader. Returns None if nothing is cached (a
    missing consensus is a valid state — reported as n/a downstream)."""
    return _read_consensus_cache(ticker)


def consensus_source(ticker: str) -> str:
    data = _read_consensus_cache(ticker)
    return data.get("source", "unknown") if data else "missing"


# ---------------------------------------------------------------------------
# Manual bank metrics (source of truth for bank-specific ratios)
# ---------------------------------------------------------------------------

MANUAL_REQUIRED_COLUMNS = [
    "period", "period_end", "nim_pct", "casa_pct", "npl_pct", "car_pct",
    "loan_growth_yoy_pct", "cost_of_credit_pct", "cost_income_pct", "source",
]
# Plausibility windows -> out-of-range values trigger loud warnings.
MANUAL_RANGES = {
    "nim_pct": (1.0, 15.0), "casa_pct": (20.0, 95.0),
    "npl_pct": (0.1, 15.0), "car_pct": (10.0, 45.0),
    "loan_growth_yoy_pct": (-30.0, 50.0), "cost_of_credit_pct": (0.0, 10.0),
    "cost_income_pct": (20.0, 90.0),
}


def load_manual_metrics(ticker: str) -> pd.DataFrame:
    """Load and validate data/manual/<TICKER>.csv. Fails loudly on missing
    columns, unparseable dates, or non-numeric metric values."""
    path = config.MANUAL_DIR / f"{ticker}.csv"
    if not path.exists():
        raise ManualDataError(
            f"Manual metrics file missing for {ticker}: {path}\n"
            f"Create it with columns: {', '.join(MANUAL_REQUIRED_COLUMNS)}")
    df = pd.read_csv(path)
    missing = [c for c in MANUAL_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ManualDataError(
            f"{path.name}: missing required column(s): {', '.join(missing)}\n"
            f"Required schema: {', '.join(MANUAL_REQUIRED_COLUMNS)}")
    if df.empty:
        raise ManualDataError(f"{path.name}: file has no data rows")
    try:
        df["period_end"] = pd.to_datetime(df["period_end"])
    except (ValueError, TypeError) as exc:
        raise ManualDataError(
            f"{path.name}: unparseable period_end date — {exc}") from exc
    numeric_cols = [c for c in MANUAL_REQUIRED_COLUMNS
                    if c.endswith("_pct")]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad = df[df[col].isna()]
        if len(bad):
            periods = ", ".join(bad["period"].astype(str))
            raise ManualDataError(
                f"{path.name}: column '{col}' has missing/non-numeric values "
                f"in period(s): {periods}")
        lo, hi = MANUAL_RANGES[col]
        offenders = df[(df[col] < lo) | (df[col] > hi)]
        for _, row in offenders.iterrows():
            print(f"  WARNING {ticker} {row['period']}: {col}={row[col]} "
                  f"outside plausible range [{lo}, {hi}] — double-check "
                  f"against the investor presentation")
    df = df.sort_values("period_end").reset_index(drop=True)
    return df


def latest_manual(ticker: str) -> pd.Series:
    """Most recent quarter of manual metrics for a bank."""
    return load_manual_metrics(ticker).iloc[-1]


def manual_is_sample(ticker: str) -> bool:
    df = load_manual_metrics(ticker)
    return df["source"].astype(str).str.contains("SAMPLE", case=False).any()


# ---------------------------------------------------------------------------
# Net foreign flow (daily net foreign buy/sell value per stock, IDR bn)
# ---------------------------------------------------------------------------
# Priority of sources, mirroring the rest of the engine:
#   1. data/manual/foreign_flow/<TICKER>.csv — analyst-exported series
#      (broker terminal / RTI / Stockbit / IDX daily trading summary export).
#      If present it IS the series (source of truth), validated and imported
#      into the cache on refresh.
#   2. Best-effort fetch of recent days from the IDX daily trading summary
#      endpoint (idx.co.id). Convenience only — the endpoint is unofficial
#      and may be unreachable; parsed values are sanity-checked and the pull
#      only fills dates missing from the cache.
#   3. Whatever the cache already holds (including the SAMPLE seed).

FLOW_REQUIRED_COLUMNS = ["date", "net_foreign_idr_bn", "source"]
# One-day |net flow| beyond this is treated as a parsing/unit error.
FLOW_SANITY_LIMIT_BN = 20_000.0  # IDR 20 tn

IDX_SUMMARY_URL = ("https://www.idx.co.id/primary/TradingSummary/"
                   "GetStockSummary?length=9999&start=0&date={date}")


def _flow_path(ticker: str) -> Path:
    return config.FLOW_CACHE_DIR / f"{ticker}.parquet"


def _flow_meta_path(ticker: str) -> Path:
    return config.FLOW_CACHE_DIR / f"{ticker}.meta.json"


def flow_source(ticker: str) -> str:
    path = _flow_meta_path(ticker)
    if not path.exists():
        return "missing"
    return json.loads(path.read_text()).get("source", "unknown")


def _write_flow_cache(ticker: str, df: pd.DataFrame, source: str) -> None:
    df = df.sort_index()
    df.index.name = "date"
    df.to_parquet(_flow_path(ticker))
    _flow_meta_path(ticker).write_text(json.dumps(
        {"source": source,
         "fetched_at": dt.datetime.now().isoformat(timespec="seconds")},
        indent=2))


def load_foreign_flow(ticker: str) -> pd.DataFrame:
    """Cache-only reader: DataFrame indexed by date with column
    net_foreign_idr_bn (positive = net foreign buying)."""
    path = _flow_path(ticker)
    if not path.exists():
        raise RuntimeError(
            f"No cached foreign flow for {ticker}. Run `python refresh.py` "
            f"(or scripts/make_sample_seed.py) first.")
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def _load_manual_flow_csv(ticker: str) -> pd.DataFrame | None:
    """Validate + normalize an analyst-provided flow CSV, if present.

    Accepts either net_foreign_idr_bn directly, or foreign_buy_idr_bn and
    foreign_sell_idr_bn from which net is derived.
    """
    path = config.MANUAL_FLOW_DIR / f"{ticker}.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path)
    has_net = "net_foreign_idr_bn" in df.columns
    has_legs = {"foreign_buy_idr_bn", "foreign_sell_idr_bn"} <= set(df.columns)
    if "date" not in df.columns or "source" not in df.columns or not (
            has_net or has_legs):
        raise ManualDataError(
            f"{path}: required columns are date, source and either "
            f"net_foreign_idr_bn or foreign_buy_idr_bn + "
            f"foreign_sell_idr_bn")
    if not has_net:
        df["net_foreign_idr_bn"] = (
            pd.to_numeric(df["foreign_buy_idr_bn"], errors="coerce")
            - pd.to_numeric(df["foreign_sell_idr_bn"], errors="coerce"))
    df["date"] = pd.to_datetime(df["date"])
    df["net_foreign_idr_bn"] = pd.to_numeric(df["net_foreign_idr_bn"],
                                             errors="coerce")
    if df["net_foreign_idr_bn"].isna().any():
        bad = df[df["net_foreign_idr_bn"].isna()]["date"].dt.date.tolist()
        raise ManualDataError(
            f"{path}: missing/non-numeric net flow on {bad[:5]}"
            + ("…" if len(bad) > 5 else ""))
    absurd = df[df["net_foreign_idr_bn"].abs() > FLOW_SANITY_LIMIT_BN]
    if len(absurd):
        raise ManualDataError(
            f"{path}: |net flow| above {FLOW_SANITY_LIMIT_BN:,.0f} IDR bn on "
            f"{absurd['date'].dt.date.tolist()[:5]} — check units "
            f"(file must be IDR *billions*)")
    out = df.set_index("date")[["net_foreign_idr_bn"]].sort_index()
    return out[~out.index.duplicated(keep="last")]


def _fetch_idx_flows_for_day(day: dt.date) -> dict[str, float] | None:
    """Best effort: one day of net foreign flow for all stocks from the IDX
    trading summary. Returns {ticker: net_idr_bn} or None on any failure."""
    try:
        import requests
        url = IDX_SUMMARY_URL.format(date=day.strftime("%Y%m%d"))
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (research; IDX banks coverage)",
            "Accept": "application/json",
        })
        if resp.status_code != 200:
            return None
        rows = resp.json().get("data") or []
        out: dict[str, float] = {}
        for row in rows:
            low = {str(k).lower(): v for k, v in row.items()}
            code = str(low.get("stockcode") or low.get("code") or "").upper()
            if code not in config.UNIVERSE:
                continue
            buy = low.get("foreignbuy")
            sell = low.get("foreignsell")
            if buy is None or sell is None:
                continue
            net_bn = (float(buy) - float(sell)) / 1e9  # IDR → IDR bn
            if abs(net_bn) > FLOW_SANITY_LIMIT_BN:
                return None  # unit mismatch — discard the whole day
            out[code] = round(net_bn, 2)
        return out or None
    except Exception:
        return None


def fetch_foreign_flow(tickers: list[str] | None = None,
                       max_backfill_days: int = 30) -> dict[str, pd.DataFrame]:
    """Refresh the foreign-flow cache per the source priority above."""
    tickers = tickers or config.TICKERS
    out: dict[str, pd.DataFrame] = {}

    manual: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = _load_manual_flow_csv(ticker)
        if df is not None:
            _write_flow_cache(ticker, df, config.SOURCE_MANUAL_CSV)
            print(f"  {ticker}: imported {len(df):,} rows from manual CSV")
            manual[ticker] = df
            out[ticker] = df
    remaining = [t for t in tickers if t not in manual]

    if remaining:
        cached: dict[str, pd.DataFrame | None] = {}
        for ticker in remaining:
            try:
                cached[ticker] = load_foreign_flow(ticker)
            except RuntimeError:
                cached[ticker] = None
        # Which recent business days are missing from every cache?
        today = dt.date.today()
        candidates = pd.bdate_range(
            today - dt.timedelta(days=max_backfill_days), today).date
        have = set()
        ref = next((c for c in cached.values() if c is not None), None)
        if ref is not None:
            have = set(ref.index.date)
        missing = [d for d in candidates if d not in have]
        fetched_days: dict[dt.date, dict[str, float]] = {}
        for day in missing:
            day_data = _fetch_idx_flows_for_day(day)
            if day_data is None:
                if not fetched_days:
                    break  # endpoint unreachable — stop trying
                continue  # holiday / empty day
            fetched_days[day] = day_data
        for ticker in remaining:
            base = cached[ticker]
            if fetched_days:
                add = pd.DataFrame({
                    "net_foreign_idr_bn": {
                        pd.Timestamp(d): v[ticker]
                        for d, v in fetched_days.items() if ticker in v}})
                merged = (add if base is None
                          else pd.concat([base, add[~add.index.isin(base.index)]]))
                _write_flow_cache(ticker, merged, config.SOURCE_IDX)
                print(f"  {ticker}: +{len(add)} days from IDX summary "
                      f"({len(merged):,} total)")
                out[ticker] = merged
            elif base is not None:
                print(f"  {ticker}: IDX endpoint unavailable — serving cache "
                      f"({len(base):,} rows, source={flow_source(ticker)})")
                out[ticker] = base
            else:
                raise RuntimeError(
                    f"No foreign flow data for {ticker}: no manual CSV, IDX "
                    f"unreachable, no cache. Run scripts/make_sample_seed.py "
                    f"or drop an export into data/manual/foreign_flow/.")
    return out


# ---------------------------------------------------------------------------
# Macro inputs
# ---------------------------------------------------------------------------

MACRO_REQUIRED_COLUMNS = ["date", "bi_rate_pct", "usdidr", "idn_10y_pct",
                          "source"]


def load_macro() -> pd.DataFrame:
    path = config.MANUAL_DIR / "macro.csv"
    if not path.exists():
        raise ManualDataError(
            f"Macro file missing: {path}\n"
            f"Create it with columns: {', '.join(MACRO_REQUIRED_COLUMNS)}")
    df = pd.read_csv(path)
    missing = [c for c in MACRO_REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ManualDataError(
            f"macro.csv: missing required column(s): {', '.join(missing)}")
    df["date"] = pd.to_datetime(df["date"])
    for col in ("bi_rate_pct", "usdidr", "idn_10y_pct"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if df[col].isna().any():
            raise ManualDataError(
                f"macro.csv: column '{col}' has missing/non-numeric values")
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Status summary (used by refresh.py)
# ---------------------------------------------------------------------------

@dataclass
class DataStatus:
    ticker: str
    price_rows: int
    price_last: str
    price_source: str
    fund_years: int
    fund_source: str
    manual_quarters: int
    manual_latest: str
    manual_sample: bool
    flow_rows: int
    flow_source: str
    consensus_source: str


def data_status() -> list[DataStatus]:
    rows = []
    for ticker in config.TICKERS:
        px = load_prices(ticker)
        fund = load_fundamentals(ticker)
        manual = load_manual_metrics(ticker)
        try:
            flow_rows = len(load_foreign_flow(ticker))
        except RuntimeError:
            flow_rows = 0
        rows.append(DataStatus(
            ticker=ticker,
            price_rows=len(px),
            price_last=str(px.index[-1].date()),
            price_source=price_source(ticker),
            fund_years=len(fund["annual"]),
            fund_source=fund.get("source", "unknown"),
            manual_quarters=len(manual),
            manual_latest=str(manual.iloc[-1]["period"]),
            manual_sample=manual_is_sample(ticker),
            flow_rows=flow_rows,
            flow_source=flow_source(ticker),
            consensus_source=consensus_source(ticker),
        ))
    return rows


def any_sample_data() -> bool:
    """True when any cache or manual file still carries sample placeholders —
    used to put an unmissable banner on every output."""
    for ticker in config.TICKERS:
        if price_source(ticker) == config.SOURCE_SAMPLE:
            return True
        if flow_source(ticker) == config.SOURCE_SAMPLE:
            return True
        if consensus_source(ticker) == config.SOURCE_SAMPLE:
            return True
        try:
            if load_fundamentals(ticker).get("source") == config.SOURCE_SAMPLE:
                return True
        except RuntimeError:
            pass
        try:
            if manual_is_sample(ticker):
                return True
        except ManualDataError:
            pass
    return False
