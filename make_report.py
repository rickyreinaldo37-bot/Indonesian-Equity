"""CLI entry point: generate an initiation-of-coverage report skeleton.

    python make_report.py BBRI
    python make_report.py BBCA --format md
    python make_report.py --all
"""
from __future__ import annotations

import argparse
import sys

from src import config
from src.report import build_report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ticker", nargs="?", help="one of: "
                    + ", ".join(config.TICKERS))
    ap.add_argument("--format", choices=("docx", "md"), default="docx")
    ap.add_argument("--all", action="store_true",
                    help="build skeletons for the whole universe")
    args = ap.parse_args()

    if not args.all and not args.ticker:
        ap.error("provide a TICKER or --all")
    tickers = config.TICKERS if args.all else [args.ticker.upper()]
    for ticker in tickers:
        if ticker not in config.UNIVERSE:
            print(f"Unknown ticker {ticker}; universe: "
                  f"{', '.join(config.TICKERS)}", file=sys.stderr)
            return 1
        path = build_report(ticker, fmt=args.format)
        print(f"Report skeleton written: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
