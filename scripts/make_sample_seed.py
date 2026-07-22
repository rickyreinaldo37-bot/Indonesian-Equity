"""Install SAMPLE placeholder data into the local cache.

Why this exists: the coverage engine is designed to pull live data from
yfinance, but it must also run end-to-end in environments with no market-data
access (CI, sandboxes, first clone). This script writes an illustrative —
NOT real — dataset into data/cache/ with every file tagged
``source = SAMPLE_SEED``. Every downstream output (Excel, charts, reports)
checks that tag and displays a sample-data warning banner.

Price paths are synthetic Brownian-bridge series anchored to approximate
historical levels; fundamentals are approximate figures in the right order of
magnitude. Treat all of it as scaffolding: run ``python refresh.py`` on a
machine with internet access and the real yfinance data replaces this seed
in place (tags flip to ``yfinance`` automatically).

Usage:  python scripts/make_sample_seed.py [--force]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402

SEED_END = "2026-07-20"

# (date, price) anchors per ticker, split-adjusted IDR. Approximate levels —
# illustrative only.
PRICE_ANCHORS: dict[str, list[tuple[str, float]]] = {
    "BBCA": [
        ("2019-01-02", 5200), ("2019-12-30", 6685), ("2020-03-23", 5100),
        ("2020-12-30", 6770), ("2021-12-30", 7300), ("2022-12-30", 8550),
        ("2023-12-28", 9400), ("2024-05-31", 10000), ("2024-09-30", 10700),
        ("2024-12-30", 9675), ("2025-04-09", 8425), ("2025-08-29", 9100),
        ("2025-12-30", 9400), ("2026-04-30", 9200), (SEED_END, 9350),
    ],
    "BBRI": [
        ("2019-01-02", 3650), ("2019-12-30", 4400), ("2020-03-23", 2800),
        ("2020-12-30", 4170), ("2021-12-30", 4110), ("2022-12-30", 4940),
        ("2023-12-28", 5725), ("2024-05-31", 4900), ("2024-12-30", 4075),
        ("2025-03-18", 3400), ("2025-07-31", 3900), ("2025-12-30", 4300),
        ("2026-03-31", 4450), (SEED_END, 4380),
    ],
    "BMRI": [
        ("2019-01-02", 3700), ("2019-12-30", 3837), ("2020-03-23", 2350),
        ("2020-12-30", 3162), ("2021-12-30", 3512), ("2022-12-30", 4963),
        ("2023-12-28", 6050), ("2024-05-31", 7200), ("2024-12-30", 5700),
        ("2025-04-09", 4650), ("2025-08-29", 5200), ("2025-12-30", 5200),
        ("2026-04-30", 5350), (SEED_END, 5300),
    ],
    "BBNI": [
        ("2019-01-02", 4400), ("2019-12-30", 3925), ("2020-03-23", 1900),
        ("2020-12-30", 3085), ("2021-12-30", 3375), ("2022-12-30", 4613),
        ("2023-12-28", 5375), ("2024-04-30", 6000), ("2024-12-30", 4350),
        ("2025-04-09", 3800), ("2025-08-29", 4400), ("2025-12-30", 4250),
        ("2026-03-31", 4400), (SEED_END, 4330),
    ],
}

DAILY_VOL = {"BBCA": 0.012, "BBRI": 0.017, "BMRI": 0.016, "BBNI": 0.017}
AVG_VOLUME = {"BBCA": 85e6, "BBRI": 210e6, "BMRI": 110e6, "BBNI": 55e6}

# Daily net foreign flow: typical one-day standard deviation, IDR bn, and the
# flow/return correlation the sample series is engineered to exhibit (the
# stylised fact for IDX blue chips: prices move with foreign money).
FLOW_STD_BN = {"BBCA": 250.0, "BBRI": 300.0, "BMRI": 180.0, "BBNI": 90.0}
FLOW_RET_CORR = 0.60

# Approximate annual fundamentals, IDR. shares are split-adjusted and held
# constant across history for simplicity (sample data only).
SHARES = {"BBCA": 123.275e9, "BBRI": 151.559e9,
          "BMRI": 93.333e9, "BBNI": 37.297e9}

FUNDAMENTALS: dict[str, dict[int, dict]] = {
    # year: (net_income, total_equity, total_assets, dps) — IDR trillions
    # except dps (IDR/share)
    "BBCA": {
        2019: (28.6, 175, 919, 68), 2020: (27.1, 184, 1076, 111),
        2021: (31.4, 203, 1228, 117), 2022: (40.7, 221, 1315, 205),
        2023: (48.6, 242, 1408, 265), 2024: (54.8, 262, 1450, 300),
        2025: (57.5, 281, 1540, 315),
    },
    "BBRI": {
        2019: (34.4, 208, 1417, 132), 2020: (18.7, 200, 1512, 120),
        2021: (30.8, 292, 1678, 98), 2022: (51.4, 304, 1865, 174),
        2023: (60.1, 318, 1965, 289), 2024: (60.2, 345, 2095, 319),
        2025: (54.5, 336, 2140, 345),
    },
    "BMRI": {
        2019: (27.5, 195, 1318, 176), 2020: (17.1, 193, 1430, 110),
        2021: (28.0, 222, 1726, 132), 2022: (41.2, 229, 1992, 180),
        2023: (55.1, 253, 2174, 265), 2024: (55.8, 277, 2427, 353),
        2025: (52.8, 292, 2510, 358),
    },
    "BBNI": {
        2019: (15.4, 125, 845, 100), 2020: (3.3, 112, 891, 20),
        2021: (10.9, 126, 964, 44), 2022: (18.3, 136, 1030, 98),
        2023: (20.9, 145, 1087, 140), 2024: (21.5, 155, 1145, 280),
        2025: (21.2, 161, 1185, 374),
    },
}


def _idx_tick(price: float) -> float:
    """IDX tick size by price band."""
    if price < 200:
        return 1
    if price < 500:
        return 2
    if price < 2000:
        return 5
    if price < 5000:
        return 10
    return 25


def _round_tick(price: float) -> float:
    tick = _idx_tick(price)
    return round(price / tick) * tick


def _bridge_path(anchors: list[tuple[str, float]], vol: float,
                 rng: np.random.Generator) -> pd.Series:
    """Log-linear interpolation between anchors plus Brownian-bridge noise
    pinned to zero at each anchor, on IDX business days."""
    closes: list[pd.Series] = []
    for (d0, p0), (d1, p1) in zip(anchors, anchors[1:]):
        days = pd.bdate_range(d0, d1)
        n = len(days)
        if n < 2:
            continue
        drift = np.linspace(np.log(p0), np.log(p1), n)
        steps = rng.normal(0, vol, n)
        walk = np.cumsum(steps)
        bridge = walk - np.linspace(0, walk[-1], n)
        seg = pd.Series(np.exp(drift + bridge), index=days)
        closes.append(seg.iloc[:-1] if (d1, p1) != anchors[-1] else seg)
    return pd.concat(closes)


def seed_prices(force: bool = False) -> None:
    rng = np.random.default_rng(20260721)
    for ticker in config.TICKERS:
        path = config.PRICE_CACHE_DIR / f"{ticker}.parquet"
        if path.exists() and not force:
            print(f"  {ticker}: price cache exists, skipping (use --force)")
            continue
        close = _bridge_path(PRICE_ANCHORS[ticker], DAILY_VOL[ticker], rng)
        close = close.apply(_round_tick)
        n = len(close)
        gap = rng.normal(0, DAILY_VOL[ticker] * 0.5, n)
        opens = (close.shift(1).fillna(close.iloc[0]) * (1 + gap)).apply(_round_tick)
        span = np.abs(rng.normal(0, DAILY_VOL[ticker], n))
        high = np.maximum(opens, close) * (1 + span * 0.6)
        low = np.minimum(opens, close) * (1 - span * 0.6)
        volume = (AVG_VOLUME[ticker] *
                  np.exp(rng.normal(0, 0.45, n))).round(-3)
        df = pd.DataFrame({
            "Open": opens.values,
            "High": [_round_tick(v) for v in high],
            "Low": [_round_tick(v) for v in low],
            "Close": close.values,
            "AdjClose": close.values,
            "Volume": volume,
        }, index=close.index)
        df.index.name = "date"
        df.to_parquet(path)
        meta = {"source": config.SOURCE_SAMPLE, "start": str(close.index[0].date()),
                "fetched_at": dt.datetime.now().isoformat(timespec="seconds")}
        (config.PRICE_CACHE_DIR / f"{ticker}.meta.json").write_text(
            json.dumps(meta, indent=2))
        print(f"  {ticker}: seeded {n:,} sample price rows "
              f"({close.index[0].date()} → {close.index[-1].date()})")


def seed_fundamentals(force: bool = False) -> None:
    for ticker in config.TICKERS:
        path = config.FUND_CACHE_DIR / f"{ticker}.json"
        if path.exists() and not force:
            print(f"  {ticker}: fundamentals cache exists, skipping")
            continue
        shares = SHARES[ticker]
        annual = {}
        for year, (ni_tn, eq_tn, ta_tn, dps) in FUNDAMENTALS[ticker].items():
            ni, eq, ta = ni_tn * 1e12, eq_tn * 1e12, ta_tn * 1e12
            annual[str(year)] = {
                "net_income": ni, "total_equity": eq, "total_assets": ta,
                "shares": shares, "eps": ni / shares, "bvps": eq / shares,
                "dps": float(dps),
            }
        payload = {
            "ticker": ticker,
            "source": config.SOURCE_SAMPLE,
            "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
            "shares_outstanding": shares,
            "annual": annual,
        }
        path.write_text(json.dumps(payload, indent=2))
        print(f"  {ticker}: seeded sample fundamentals "
              f"({len(annual)} fiscal years)")


def seed_foreign_flow(force: bool = False) -> None:
    """Daily net foreign flow (IDR bn) engineered to correlate with the
    seeded price returns at ~FLOW_RET_CORR, so the flow exhibits demonstrate
    the foreign-flow/price relationship on sample data too."""
    rng = np.random.default_rng(20260722)
    out_dir = config.CACHE_DIR / "foreign_flow"
    out_dir.mkdir(parents=True, exist_ok=True)
    for ticker in config.TICKERS:
        path = out_dir / f"{ticker}.parquet"
        if path.exists() and not force:
            print(f"  {ticker}: foreign flow cache exists, skipping")
            continue
        px_path = config.PRICE_CACHE_DIR / f"{ticker}.parquet"
        if not px_path.exists():
            raise RuntimeError("Seed prices before foreign flow")
        close = pd.read_parquet(px_path)["Close"]
        ret = close.pct_change().fillna(0.0)
        z = (ret - ret.mean()) / ret.std()
        k = FLOW_RET_CORR
        noise = rng.normal(0, 1, len(z))
        flow = FLOW_STD_BN[ticker] * (k * z.values
                                      + np.sqrt(1 - k ** 2) * noise)
        df = pd.DataFrame({"net_foreign_idr_bn": np.round(flow, 1)},
                          index=close.index)
        df.index.name = "date"
        df.to_parquet(path)
        meta = {"source": config.SOURCE_SAMPLE,
                "fetched_at": dt.datetime.now().isoformat(timespec="seconds")}
        (out_dir / f"{ticker}.meta.json").write_text(json.dumps(meta, indent=2))
        realized = float(np.corrcoef(flow, ret.values)[0, 1])
        print(f"  {ticker}: seeded {len(df):,} sample flow rows "
              f"(realized corr vs returns {realized:.2f})")


def seed_all(force: bool = False) -> None:
    print("Seeding SAMPLE data cache (illustrative figures — not real "
          "market data):")
    seed_prices(force)
    seed_fundamentals(force)
    seed_foreign_flow(force)
    print("Sample seed complete. Run `python refresh.py` with internet "
          "access to replace it with live yfinance data.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing cache files")
    args = ap.parse_args()
    seed_all(force=args.force)
