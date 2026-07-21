"""One-command data refresh for the IDX Banks Coverage Engine.

    python refresh.py            # fetch prices + fundamentals, validate inputs
    python refresh.py --force    # ignore same-day cache, re-pull everything

Behaviour without network access: existing caches are served as-is; if no
cache exists at all, the SAMPLE seed is installed automatically (loudly
labeled). All outputs downstream disclose their data source.
"""
from __future__ import annotations

import argparse
import sys

from src import config, fetch


def _rule(char: str = "-") -> None:
    print(char * 78)


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh all coverage data")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if cache is fresh today")
    ap.add_argument("--start", default=config.PRICE_START,
                    help=f"price history start date (default {config.PRICE_START})")
    args = ap.parse_args()

    _rule("=")
    print("IDX BANKS COVERAGE ENGINE — data refresh")
    _rule("=")

    # 1) Prices ------------------------------------------------------------
    print("\n[1/4] Daily prices (yfinance, cached to parquet)")
    try:
        fetch.fetch_prices(config.TICKERS, start=args.start, force=args.force)
    except RuntimeError as exc:
        if "no local cache" in str(exc).lower() or "No price data" in str(exc):
            print("  No cache and no network — installing SAMPLE seed …")
            from scripts.make_sample_seed import seed_all
            seed_all()
            for ticker in config.TICKERS:
                fetch.load_prices(ticker)
        else:
            raise

    # 2) Fundamentals ------------------------------------------------------
    print("\n[2/4] Fundamentals (yfinance income statement / balance sheet)")
    for ticker in config.TICKERS:
        try:
            fetch.fetch_fundamentals(ticker, force=args.force)
        except RuntimeError:
            print(f"  {ticker}: no fundamentals cache — installing SAMPLE seed …")
            from scripts.make_sample_seed import seed_fundamentals
            seed_fundamentals()
            fetch.fetch_fundamentals(ticker)

    # 3) Manual metrics ----------------------------------------------------
    print("\n[3/4] Manual bank metrics (data/manual/<TICKER>.csv)")
    try:
        for ticker in config.TICKERS:
            df = fetch.load_manual_metrics(ticker)
            print(f"  {ticker}: {len(df)} quarters, latest "
                  f"{df.iloc[-1]['period']}")
    except fetch.ManualDataError as exc:
        print(f"\nMANUAL DATA ERROR\n{exc}", file=sys.stderr)
        return 1

    # 4) Macro -------------------------------------------------------------
    print("\n[4/4] Macro inputs (data/manual/macro.csv)")
    try:
        macro = fetch.load_macro()
    except fetch.ManualDataError as exc:
        print(f"\nMACRO DATA ERROR\n{exc}", file=sys.stderr)
        return 1
    latest = macro.iloc[-1]
    print(f"  {len(macro)} rows, latest {latest['date'].date()}: "
          f"BI rate {latest['bi_rate_pct']:.2f}%, "
          f"USD/IDR {latest['usdidr']:,.0f}, "
          f"10Y {latest['idn_10y_pct']:.2f}%")

    # Status summary -------------------------------------------------------
    print()
    _rule()
    print(f"{'':<6}{'px rows':>8} {'px last':>11} {'px source':>12} "
          f"{'FY yrs':>7} {'fund source':>12} {'qtrs':>5} {'latest':>7}")
    _rule()
    for s in fetch.data_status():
        print(f"{s.ticker:<6}{s.price_rows:>8,} {s.price_last:>11} "
              f"{s.price_source:>12} {s.fund_years:>7} {s.fund_source:>12} "
              f"{s.manual_quarters:>5} {s.manual_latest:>7}")
    _rule()

    if fetch.any_sample_data():
        print(
            "\n*** WARNING: SAMPLE DATA IN USE ***\n"
            "Some inputs are illustrative placeholders (source=SAMPLE_SEED or\n"
            "manual rows tagged SAMPLE). Every output will carry a sample-data\n"
            "banner. Replace with real data before publishing:\n"
            "  - run `python refresh.py --force` on a machine with internet\n"
            "    access (prices + fundamentals), and\n"
            "  - transcribe real quarterly metrics into data/manual/*.csv\n")
    else:
        print("\nAll data sources live. Ready: python comps.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
