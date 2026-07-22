"""Forward earnings, consensus target price, and forward P/E.

Two distinct, clearly-labeled things live here — the codebase never conflates
them:

1. **The analyst's own 12-month forward view.** Forward EPS is the analyst's
   own FY+1 estimate from assumptions/<TICKER>.yaml (`forward_eps`); there is
   no consensus feed behind it. From it we derive forward net income, YoY
   earnings growth, and forward P/E, and cross-check against the residual
   income model's own year-1 implied EPS (ROE_start x BVPS_0).

2. **Sell-side consensus.** Target price, analyst count, rating and consensus
   forward EPS come from a real source only: an analyst-sourced override in
   assumptions/<TICKER>.yaml (`consensus` block, highest priority) or the
   yfinance consensus cache. Consensus is NEVER fabricated — when no real
   source is available every consensus field is reported as n/a, and any
   SAMPLE placeholder is loudly tagged so it can't be mistaken for real data.

Run:  python -m src.forwards [TICKER ...]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

from src import config, fetch, valuation


@dataclass
class ForwardView:
    ticker: str
    last_close: float
    price_date: str
    shares: float
    # Trailing (last reported FY)
    trailing_fy_label: str
    trailing_eps: float
    trailing_ni_tn: float
    trailing_pe: float
    # Forward — analyst's own estimate
    fwd_eps_own: float | None
    fwd_ni_own_tn: float | None
    eps_growth_pct: float | None
    fwd_pe_own: float | None
    # Residual income model year-1 EPS (internal cross-check)
    model_year1_eps: float
    # Consensus (real source only)
    consensus_available: bool
    consensus_source: str | None
    consensus_is_sample: bool
    target_mean: float | None
    target_high: float | None
    target_low: float | None
    upside_to_target_pct: float | None
    num_analysts: int | None
    recommendation: str | None
    consensus_fwd_eps: float | None
    fwd_pe_consensus: float | None


def _resolve_consensus(ticker: str, assumptions: dict) -> dict:
    """Consensus resolution with source priority:
      1. assumptions.yaml `consensus` override (analyst-sourced) — target set
      2. yfinance / SAMPLE consensus cache
      3. none available
    Returns a normalized dict incl. `available`, `source`, `is_sample`.
    """
    blank = {"available": False, "source": None, "is_sample": False,
             "target_mean": None, "target_high": None, "target_low": None,
             "num_analysts": None, "recommendation": None,
             "consensus_fwd_eps": None}

    override = (assumptions or {}).get("consensus") or {}
    if override.get("target_price_idr") is not None:
        return {**blank, "available": True,
                "source": override.get("source") or "manual (assumptions.yaml)",
                "target_mean": float(override["target_price_idr"]),
                "num_analysts": override.get("num_analysts")}

    cache = fetch.load_consensus(ticker)
    if cache and cache.get("target_mean") is not None:
        return {"available": True,
                "source": cache.get("source"),
                "is_sample": cache.get("source") == config.SOURCE_SAMPLE,
                "target_mean": cache.get("target_mean"),
                "target_high": cache.get("target_high"),
                "target_low": cache.get("target_low"),
                "num_analysts": cache.get("num_analysts"),
                "recommendation": cache.get("recommendation_key"),
                "consensus_fwd_eps": cache.get("consensus_forward_eps")}
    return blank


def forward_view(ticker: str) -> ForwardView:
    a = valuation.load_assumptions(ticker)
    fund = fetch.fundamentals_frame(ticker)
    fdata = fetch.load_fundamentals(ticker)
    shares = float(fdata["shares_outstanding"])
    close, price_date = fetch.last_close(ticker)

    latest_fy = int(fund.index[-1])
    trailing_eps = float(fund.loc[latest_fy, "eps"])
    trailing_ni_tn = float(fund.loc[latest_fy, "net_income"]) / 1e12

    fwd_eps_own = a.get("forward_eps")
    fwd_eps_own = float(fwd_eps_own) if fwd_eps_own else None
    fwd_ni_own_tn = (fwd_eps_own * shares / 1e12) if fwd_eps_own else None
    eps_growth = (100 * (fwd_eps_own / trailing_eps - 1)
                  if fwd_eps_own else None)
    fwd_pe_own = (close / fwd_eps_own) if fwd_eps_own else None

    # Model-implied year-1 EPS = ROE_start x opening BVPS (same basis as the
    # RI forecast path's first year) — a consistency check on the own estimate.
    bvps_0 = (float(a["bvps_override"]) if a.get("bvps_override")
              else float(fund.loc[latest_fy, "bvps"]))
    model_year1_eps = a["residual_income"]["roe_start_pct"] / 100 * bvps_0

    c = _resolve_consensus(ticker, a)
    target = c["target_mean"]
    upside = (100 * (target / close - 1)) if target else None
    cons_fwd_eps = c["consensus_fwd_eps"]
    fwd_pe_cons = (close / cons_fwd_eps) if cons_fwd_eps else None
    n = c["num_analysts"]

    return ForwardView(
        ticker=ticker, last_close=close, price_date=str(price_date.date()),
        shares=shares,
        trailing_fy_label=f"FY{latest_fy % 100}",
        trailing_eps=trailing_eps, trailing_ni_tn=trailing_ni_tn,
        trailing_pe=close / trailing_eps,
        fwd_eps_own=fwd_eps_own, fwd_ni_own_tn=fwd_ni_own_tn,
        eps_growth_pct=eps_growth, fwd_pe_own=fwd_pe_own,
        model_year1_eps=model_year1_eps,
        consensus_available=c["available"], consensus_source=c["source"],
        consensus_is_sample=c["is_sample"],
        target_mean=target, target_high=c["target_high"],
        target_low=c["target_low"], upside_to_target_pct=upside,
        num_analysts=int(n) if n else None,
        recommendation=c["recommendation"],
        consensus_fwd_eps=cons_fwd_eps, fwd_pe_consensus=fwd_pe_cons,
    )


def _fmt(v, unit="", dp=1):
    if v is None:
        return "n/a"
    return f"{v:,.{dp}f}{unit}"


def print_forward(fv: ForwardView) -> None:
    print("=" * 72)
    print(f"{fv.ticker} — 12-month forward earnings & consensus "
          f"(close {fv.last_close:,.0f} @ {fv.price_date})")
    print("=" * 72)
    print(f"Trailing {fv.trailing_fy_label}: EPS {fv.trailing_eps:,.0f}  "
          f"NI {fv.trailing_ni_tn:,.1f} tn  P/E {fv.trailing_pe:.1f}x")
    print("\nAnalyst's own FY+1 estimate (from assumptions.yaml):")
    print(f"  Forward EPS       {_fmt(fv.fwd_eps_own, ' IDR', 0)}   "
          f"(model year-1 implied {_fmt(fv.model_year1_eps, '', 0)})")
    print(f"  Forward net income {_fmt(fv.fwd_ni_own_tn, ' IDR tn')}")
    print(f"  EPS growth YoY    {_fmt(fv.eps_growth_pct, '%')}")
    print(f"  Forward P/E       {_fmt(fv.fwd_pe_own, 'x')}   (own est.)")
    print("\nSell-side consensus:")
    if not fv.consensus_available:
        print("  n/a — no consensus source (set the consensus block in "
              "assumptions.yaml or refresh yfinance)")
    else:
        tag = "  [SAMPLE — illustrative, NOT real consensus]" \
            if fv.consensus_is_sample else ""
        print(f"  Target price      {_fmt(fv.target_mean, ' IDR', 0)}  "
              f"(range {_fmt(fv.target_low, '', 0)}–"
              f"{_fmt(fv.target_high, '', 0)}){tag}")
        print(f"  Upside to target  {_fmt(fv.upside_to_target_pct, '%')}")
        print(f"  # analysts        {fv.num_analysts or 'n/a'}   "
              f"rating: {fv.recommendation or 'n/a'}")
        print(f"  Consensus fwd P/E {_fmt(fv.fwd_pe_consensus, 'x')}  "
              f"(consensus EPS {_fmt(fv.consensus_fwd_eps, '', 0)})")
        print(f"  Source: {fv.consensus_source}")
    print()


def main() -> int:
    tickers = [t.upper() for t in sys.argv[1:]] or config.TICKERS
    for ticker in tickers:
        if ticker not in config.UNIVERSE:
            print(f"Unknown ticker {ticker}", file=sys.stderr)
            return 1
        print_forward(forward_view(ticker))
    return 0


if __name__ == "__main__":
    sys.exit(main())
