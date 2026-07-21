"""F3 — Valuation models: Residual Income (primary) + DDM cross-check.

All inputs come from one source of truth per bank: assumptions/<TICKER>.yaml.
Change a number there and it flows through fair value, the sensitivity
table, the comps workbook, and the report skeleton with no manual edits.

Model notes
-----------
Residual income (appropriate for banks — value is anchored on book):

    FV = BVPS_0 + Σ PV(RI_t) + PV(terminal RI)
    RI_t = (ROE_t − COE) × BVPS_{t−1}

ROE fades linearly from `roe_start_pct` (year 1) to `roe_terminal_pct`
(final forecast year), book compounds under clean surplus
(BV_t = BV_{t−1} + EPS_t − DPS_t). Beyond the horizon, residual income grows
at `terminal_growth_pct` with the payout implied by sustainable growth
(payout_term = 1 − g/ROE_term), so the RI and DDM terminal states are
mutually consistent — under clean surplus both models return identical fair
value, which the unit tests assert.

Cost of equity: CAPM with Indonesia inputs — COE = rf + β × ERP — or an
explicit `coe_override_pct`.

Run:  python -m src.valuation [TICKER ...]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yaml

from src import config, fetch


class AssumptionsError(Exception):
    """Raised when an assumptions file is missing or malformed."""


class ValuationError(Exception):
    """Raised when inputs are economically invalid (e.g. COE <= g)."""


# ---------------------------------------------------------------------------
# Assumptions (single source of truth)
# ---------------------------------------------------------------------------

REQUIRED_KEYS = [
    ("cost_of_equity", "risk_free_pct"),
    ("cost_of_equity", "equity_risk_premium_pct"),
    ("cost_of_equity", "beta"),
    ("residual_income", "forecast_years"),
    ("residual_income", "roe_start_pct"),
    ("residual_income", "roe_terminal_pct"),
    ("residual_income", "payout_ratio_pct"),
    ("residual_income", "terminal_growth_pct"),
]


def load_assumptions(ticker: str) -> dict:
    path = config.ASSUMPTIONS_DIR / f"{ticker}.yaml"
    if not path.exists():
        raise AssumptionsError(
            f"Assumptions file missing for {ticker}: {path}")
    with open(path) as fh:
        data = yaml.safe_load(fh)
    missing = [".".join(keys) for keys in REQUIRED_KEYS
               if _dig(data, keys) is None]
    if missing:
        raise AssumptionsError(
            f"{path.name}: missing required key(s): {', '.join(missing)}")
    payout = data["residual_income"]["payout_ratio_pct"]
    if not 0 <= payout <= 100:
        raise AssumptionsError(
            f"{path.name}: payout_ratio_pct must be within [0, 100], "
            f"got {payout}")
    return data


def _dig(data: dict, keys: tuple[str, ...]):
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def capm_coe(assumptions: dict) -> float:
    """Cost of equity in percent. CAPM unless coe_override_pct is set."""
    coe = assumptions["cost_of_equity"]
    if coe.get("coe_override_pct") is not None:
        return float(coe["coe_override_pct"])
    return float(coe["risk_free_pct"]
                 + coe["beta"] * coe["equity_risk_premium_pct"])


# ---------------------------------------------------------------------------
# Core model math (pure functions — unit-tested against hand calcs)
# ---------------------------------------------------------------------------

def roe_fade_path(start_pct: float, terminal_pct: float,
                  years: int) -> list[float]:
    """Linear ROE path from start (year 1) to terminal (year N)."""
    if years < 1:
        raise ValuationError(f"forecast_years must be >= 1, got {years}")
    if years == 1:
        return [terminal_pct]
    return list(np.linspace(start_pct, terminal_pct, years))


def _validate_terminal(coe_pct: float, growth_pct: float,
                       roe_terminal_pct: float) -> None:
    if coe_pct <= growth_pct:
        raise ValuationError(
            f"Cost of equity ({coe_pct:.2f}%) must exceed terminal growth "
            f"({growth_pct:.2f}%) — perpetuity is undefined otherwise.")
    if roe_terminal_pct <= growth_pct:
        raise ValuationError(
            f"Terminal ROE ({roe_terminal_pct:.2f}%) must exceed terminal "
            f"growth ({growth_pct:.2f}%): sustainable growth g = ROE × "
            f"(1 − payout) is impossible otherwise.")


def _forecast_path(bvps_0: float, roe_path_pct: list[float],
                   payout_pct: float, coe_pct: float) -> pd.DataFrame:
    """Year-by-year clean-surplus forecast shared by RI and DDM."""
    rows = []
    bv = bvps_0
    coe = coe_pct / 100
    for t, roe_pct in enumerate(roe_path_pct, start=1):
        eps = roe_pct / 100 * bv
        dps = payout_pct / 100 * eps
        ri = eps - coe * bv
        bv_close = bv + eps - dps
        disc = (1 + coe) ** t
        rows.append({
            "year": t, "roe_pct": roe_pct, "bvps_open": bv, "eps": eps,
            "dps": dps, "bvps_close": bv_close, "ri": ri,
            "pv_ri": ri / disc, "pv_dps": dps / disc,
        })
        bv = bv_close
    return pd.DataFrame(rows)


def residual_income_value(bvps_0: float, coe_pct: float,
                          roe_path_pct: list[float], payout_pct: float,
                          terminal_growth_pct: float) -> tuple[float, pd.DataFrame, dict]:
    """Residual income fair value per share.

    Returns (fair_value, forecast_path, terminal_detail).
    """
    roe_term = roe_path_pct[-1]
    _validate_terminal(coe_pct, terminal_growth_pct, roe_term)
    path = _forecast_path(bvps_0, roe_path_pct, payout_pct, coe_pct)
    coe, g = coe_pct / 100, terminal_growth_pct / 100
    n = len(path)
    bv_n = path["bvps_close"].iloc[-1]
    ri_next = (roe_term / 100 - coe) * bv_n
    tv = ri_next / (coe - g)
    pv_tv = tv / (1 + coe) ** n
    fv = bvps_0 + path["pv_ri"].sum() + pv_tv
    terminal = {
        "payout_terminal_pct": 100 * (1 - g / (roe_term / 100)),
        "ri_next": ri_next, "terminal_value": tv, "pv_terminal": pv_tv,
        "justified_terminal_pb": (roe_term / 100 - g) / (coe - g),
    }
    return fv, path, terminal


def ddm_value(bvps_0: float, coe_pct: float, roe_path_pct: list[float],
              payout_pct: float, terminal_growth_pct: float) -> tuple[float, pd.DataFrame]:
    """Dividend discount fair value per share on the same forecast path.

    Terminal payout is the sustainable-growth payout (1 − g/ROE_term), so the
    terminal state matches the residual income model.
    """
    roe_term = roe_path_pct[-1]
    _validate_terminal(coe_pct, terminal_growth_pct, roe_term)
    path = _forecast_path(bvps_0, roe_path_pct, payout_pct, coe_pct)
    coe, g = coe_pct / 100, terminal_growth_pct / 100
    n = len(path)
    bv_n = path["bvps_close"].iloc[-1]
    payout_term = 1 - g / (roe_term / 100)
    dps_next = roe_term / 100 * bv_n * payout_term
    tv = dps_next / (coe - g)
    fv = path["pv_dps"].sum() + tv / (1 + coe) ** n
    return fv, path


def sensitivity_table(bvps_0: float, coe_pct: float,
                      roe_terminal_pct: float, roe_start_pct: float,
                      years: int, payout_pct: float,
                      terminal_growth_pct: float,
                      coe_span: float = 1.0, coe_step: float = 0.5,
                      roe_span: float = 2.0, roe_step: float = 1.0) -> pd.DataFrame:
    """RI fair value grid: COE (rows) × terminal ROE (columns)."""
    coes = np.round(np.arange(coe_pct - coe_span, coe_pct + coe_span + 1e-9,
                              coe_step), 2)
    roes = np.round(np.arange(roe_terminal_pct - roe_span,
                              roe_terminal_pct + roe_span + 1e-9, roe_step), 2)
    grid = {}
    for roe_t in roes:
        col = []
        for coe in coes:
            try:
                fv, _, _ = residual_income_value(
                    bvps_0, coe, roe_fade_path(roe_start_pct, roe_t, years),
                    payout_pct, terminal_growth_pct)
            except ValuationError:
                fv = np.nan
            col.append(fv)
        grid[f"{roe_t:.1f}%"] = col
    table = pd.DataFrame(grid, index=[f"{c:.2f}%" for c in coes])
    table.index.name = "COE \\ terminal ROE"
    return table


# ---------------------------------------------------------------------------
# Bank-level orchestration
# ---------------------------------------------------------------------------

@dataclass
class ValuationResult:
    ticker: str
    coe_pct: float
    bvps_0: float
    last_close: float
    price_date: str
    ri_fair_value: float
    ddm_fair_value: float
    implied_pb: float
    upside_pct: float
    justified_terminal_pb: float
    payout_terminal_pct: float
    ri_path: pd.DataFrame
    terminal: dict
    sensitivity: pd.DataFrame
    assumptions: dict = field(repr=False)


def value_bank(ticker: str) -> ValuationResult:
    a = load_assumptions(ticker)
    coe = capm_coe(a)
    ri = a["residual_income"]

    if a.get("bvps_override"):
        bvps_0 = float(a["bvps_override"])
    else:
        fund = fetch.fundamentals_frame(ticker)
        bvps_0 = float(fund["bvps"].iloc[-1])

    close, price_date = fetch.last_close(ticker)
    path_pct = roe_fade_path(ri["roe_start_pct"], ri["roe_terminal_pct"],
                             int(ri["forecast_years"]))
    fv_ri, path, terminal = residual_income_value(
        bvps_0, coe, path_pct, ri["payout_ratio_pct"],
        ri["terminal_growth_pct"])
    fv_ddm, _ = ddm_value(bvps_0, coe, path_pct, ri["payout_ratio_pct"],
                          ri["terminal_growth_pct"])
    sens = sensitivity_table(
        bvps_0, coe, ri["roe_terminal_pct"], ri["roe_start_pct"],
        int(ri["forecast_years"]), ri["payout_ratio_pct"],
        ri["terminal_growth_pct"])
    return ValuationResult(
        ticker=ticker,
        coe_pct=coe,
        bvps_0=bvps_0,
        last_close=close,
        price_date=str(price_date.date()),
        ri_fair_value=fv_ri,
        ddm_fair_value=fv_ddm,
        implied_pb=fv_ri / bvps_0,
        upside_pct=100 * (fv_ri / close - 1),
        justified_terminal_pb=terminal["justified_terminal_pb"],
        payout_terminal_pct=terminal["payout_terminal_pct"],
        ri_path=path,
        terminal=terminal,
        sensitivity=sens,
        assumptions=a,
    )


def print_valuation(res: ValuationResult) -> None:
    a = res.assumptions
    coe_a = a["cost_of_equity"]
    print("=" * 72)
    print(f"{res.ticker} — residual income valuation "
          f"(close {res.last_close:,.0f} @ {res.price_date})")
    print("=" * 72)
    if coe_a.get("coe_override_pct") is not None:
        print(f"COE: {res.coe_pct:.2f}% (explicit override)")
    else:
        print(f"COE: {res.coe_pct:.2f}%  =  rf {coe_a['risk_free_pct']:.2f}% "
              f"+ β {coe_a['beta']:.2f} × ERP "
              f"{coe_a['equity_risk_premium_pct']:.2f}%")
    print(f"BVPS_0: {res.bvps_0:,.0f}   payout (horizon): "
          f"{a['residual_income']['payout_ratio_pct']:.0f}%   terminal g: "
          f"{a['residual_income']['terminal_growth_pct']:.1f}%   terminal "
          f"payout: {res.payout_terminal_pct:.1f}%")
    with pd.option_context("display.float_format", "{:,.1f}".format):
        print(res.ri_path[["year", "roe_pct", "bvps_open", "eps", "dps",
                           "ri", "pv_ri"]].to_string(index=False))
    print(f"PV explicit RI: {res.ri_path['pv_ri'].sum():,.0f}   "
          f"PV terminal: {res.terminal['pv_terminal']:,.0f} "
          f"(justified terminal P/B {res.justified_terminal_pb:.2f}x)")
    print(f"\nRI fair value:  {res.ri_fair_value:,.0f}  "
          f"(implied P/B {res.implied_pb:.2f}x)")
    print(f"DDM cross-check: {res.ddm_fair_value:,.0f}")
    print(f"Upside/(downside) vs close: {res.upside_pct:+.1f}%")
    print("\nSensitivity — RI fair value (COE rows × terminal ROE cols):")
    with pd.option_context("display.float_format", "{:,.0f}".format):
        print(res.sensitivity.to_string())
    print()


def main() -> int:
    tickers = sys.argv[1:] or config.TICKERS
    for ticker in tickers:
        ticker = ticker.upper()
        if ticker not in config.UNIVERSE:
            print(f"Unknown ticker {ticker}; universe: "
                  f"{', '.join(config.TICKERS)}", file=sys.stderr)
            return 1
        print_valuation(value_bank(ticker))
    return 0


if __name__ == "__main__":
    sys.exit(main())
