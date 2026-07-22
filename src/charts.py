"""F4 — Report-ready charts in one consistent house style.

Every chart shares the same anatomy: left-aligned bold title with a muted
subtitle, recessive y-only grid, no top/right spines, per-bank fixed colors
AND fixed marker shapes (color-independent identity for print/grayscale/CVD),
a source line bottom-left, the analyst watermark bottom-right, and — when the
underlying cache is sample data — an unmissable red SAMPLE tag.

Outputs are 300-dpi PNGs:
    output/charts/sector/    cross-bank exhibits
    output/charts/<TICKER>/  per-bank exhibits

Run:  python -m src.charts
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

from src import config, fetch, flows

# House ink & surface tokens (text never wears series colors)
INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#8a897f"
GRID = "#e8e8e6"
SPINE = "#c9c9c6"
RED = "#c00000"

DPI = 300
FIGSIZE = (9.0, 5.0)


def apply_house_style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9.5,
        "text.color": INK,
        "axes.edgecolor": SPINE,
        "axes.labelcolor": INK_2,
        "axes.titlesize": 13,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "axes.axisbelow": True,
        "xtick.color": INK_2,
        "ytick.color": INK_2,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    })


def _new_axes(legend_room: bool = False):
    fig, ax = plt.subplots(figsize=FIGSIZE)
    fig.subplots_adjust(top=0.84, bottom=0.24 if legend_room else 0.15,
                        left=0.07, right=0.93)
    ax.grid(axis="y")
    ax.grid(False, axis="x")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    return fig, ax


def _chrome(fig, title: str, subtitle: str, source: str) -> None:
    """Title block, footer, watermark, sample tag — identical on every chart."""
    fig.text(0.07, 0.945, title, fontsize=13, fontweight="bold", color=INK,
             ha="left")
    fig.text(0.07, 0.895, subtitle, fontsize=9, color=INK_2, ha="left")
    fig.text(0.07, 0.025, f"Source: {source}", fontsize=7.5, color=INK_MUTED,
             ha="left")
    fig.text(0.93, 0.025, config.WATERMARK, fontsize=7.5, color=INK_MUTED,
             ha="right")
    if fetch.any_sample_data():
        fig.text(0.93, 0.945, "SAMPLE DATA — ILLUSTRATIVE", fontsize=8,
                 fontweight="bold", color=RED, ha="right",
                 bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                           edgecolor=RED, linewidth=1.2))


def _source_line() -> str:
    if fetch.any_sample_data():
        return ("SAMPLE seed data (illustrative) — refresh with yfinance "
                "before publication")
    return "Yahoo Finance (yfinance), company reports, author calculations"


def _spread_labels(ys: list[float], min_gap: float) -> list[float]:
    """Nudge overlapping end-label y-positions apart (simple 1-D relaxation)."""
    order = np.argsort(ys)
    adj = list(map(float, ys))
    for _ in range(50):
        moved = False
        for a, b in zip(order, order[1:]):
            if adj[b] - adj[a] < min_gap:
                push = (min_gap - (adj[b] - adj[a])) / 2
                adj[a] -= push
                adj[b] += push
                moved = True
        if not moved:
            break
    return adj


def _end_labels(ax, ends: dict[str, tuple[float, float, str]]) -> None:
    """Direct labels at line ends, in ink (identity never color-alone).

    ends: ticker -> (x, y, text)
    """
    ymin, ymax = ax.get_ylim()
    gap = (ymax - ymin) * 0.045
    ys = _spread_labels([v[1] for v in ends.values()], gap)
    span = ax.get_xlim()[1] - ax.get_xlim()[0]
    for (ticker, (x, _, text)), y in zip(ends.items(), ys):
        ax.annotate(text, xy=(x + span * 0.012, y), fontsize=8,
                    fontweight="bold", color=INK, va="center",
                    annotation_clip=False)


def _legend_below(ax, ncol: int = 4) -> None:
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, -0.10), ncol=ncol,
              columnspacing=1.6, handlelength=1.8)


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# Sector charts
# ---------------------------------------------------------------------------

def chart_price_rebased(years: int = 3) -> Path:
    apply_house_style()
    fig, ax = _new_axes(legend_room=True)

    closes = {t: fetch.load_prices(t)["Close"].dropna()
              for t in config.TICKERS}
    end = max(s.index[-1] for s in closes.values())
    start = end - pd.DateOffset(years=years)
    ends: dict[str, tuple[float, float, str]] = {}
    for ticker, px in closes.items():
        px = px[px.index >= start]
        rebased = 100 * px / px.iloc[0]
        info = config.UNIVERSE[ticker]
        ax.plot(rebased.index, rebased.values, color=info["color"], lw=2.2,
                label=ticker, marker=info["marker"], markersize=5,
                markevery=max(1, len(rebased) // 14), zorder=3)
        ends[ticker] = (mdates.date2num(rebased.index[-1]),
                        float(rebased.iloc[-1]),
                        f"{ticker} {rebased.iloc[-1]:,.0f}")
    ax.axhline(100, color=SPINE, lw=1.0, zorder=1)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(
        mdates.AutoDateLocator()))
    ax.set_xlim(mdates.date2num(start), mdates.date2num(end)
                + (mdates.date2num(end) - mdates.date2num(start)) * 0.09)
    _end_labels(ax, ends)
    _legend_below(ax)
    _chrome(fig, f"IDX banks — {years}-year price performance",
            f"Total price return indexed to 100 at "
            f"{start:%b %Y}  |  through {end:%d %b %Y}", _source_line())
    return _save(fig, config.CHART_DIR / "sector" / "price_rebased.png")


def chart_roe_pb_scatter(comps_table: pd.DataFrame | None = None) -> Path:
    """The classic bank-valuation chart: profitability vs multiple."""
    if comps_table is None:
        from src.comps import build_comps
        comps_table = build_comps().table
    apply_house_style()
    fig, ax = _new_axes()

    xs = comps_table["roe_pct"].astype(float)
    ys = comps_table["pb"].astype(float)
    for ticker in config.TICKERS:
        info = config.UNIVERSE[ticker]
        ax.scatter(xs[ticker], ys[ticker], s=130, color=info["color"],
                   marker=info["marker"], zorder=3, edgecolor="white",
                   linewidth=1.2)
        ax.annotate(ticker, xy=(xs[ticker], ys[ticker]),
                    xytext=(8, 6), textcoords="offset points",
                    fontsize=9, fontweight="bold", color=INK)

    slope, intercept = np.polyfit(xs, ys, 1)
    fit_x = np.linspace(xs.min() - 1.2, xs.max() + 1.2, 50)
    ax.plot(fit_x, slope * fit_x + intercept, ls="--", lw=1.4, color=INK_MUTED,
            zorder=2)
    r = np.corrcoef(xs, ys)[0, 1]
    ax.annotate(f"P/B = {intercept:+.2f} + {slope:.2f} × ROE   "
                f"(R² = {r**2:.2f})",
                xy=(0.02, 0.95), xycoords="axes fraction", fontsize=8,
                color=INK_2)
    ax.set_xlabel("ROE (latest FY, %)")
    ax.set_ylabel("P/B (x)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}x"))
    ax.set_xlim(xs.min() - 2, xs.max() + 2)
    ax.set_ylim(0, ys.max() * 1.18)
    _chrome(fig, "ROE vs P/B — who earns their multiple?",
            "Latest fiscal-year ROE vs current price-to-book, with OLS fit",
            _source_line())
    return _save(fig, config.CHART_DIR / "sector" / "roe_vs_pb.png")


def _quarterly_lines(metric: str, title: str, subtitle: str,
                     fname: str, fmt: str = "{v:.1f}") -> Path:
    apply_house_style()
    fig, ax = _new_axes(legend_room=True)
    ends: dict[str, tuple[float, float, str]] = {}
    periods_ref: list[str] = []
    for ticker in config.TICKERS:
        manual = fetch.load_manual_metrics(ticker)
        info = config.UNIVERSE[ticker]
        xs = np.arange(len(manual))
        ax.plot(xs, manual[metric], color=info["color"], lw=2.2,
                label=ticker, marker=info["marker"], markersize=5.5, zorder=3)
        last_v = float(manual[metric].iloc[-1])
        ends[ticker] = (float(xs[-1]), last_v,
                        f"{ticker} " + fmt.format(v=last_v))
        if len(manual) > len(periods_ref):
            periods_ref = list(manual["period"])
    ax.set_xticks(np.arange(len(periods_ref)))
    ax.set_xticklabels(periods_ref, rotation=0)
    ax.set_xlim(-0.4, len(periods_ref) - 1 + len(periods_ref) * 0.11)
    _end_labels(ax, ends)
    _legend_below(ax)
    _chrome(fig, title, subtitle, "Company investor presentations "
            "(manual data layer)" + (" — SAMPLE placeholders"
                                     if fetch.any_sample_data() else ""))
    return _save(fig, config.CHART_DIR / "sector" / fname)


def chart_nim_trend() -> Path:
    return _quarterly_lines(
        "nim_pct", "Net interest margin by quarter",
        "NIM (%), as disclosed in quarterly investor presentations",
        "nim_trend.png", "{v:.1f}%")


def chart_loan_growth_trend() -> Path:
    return _quarterly_lines(
        "loan_growth_yoy_pct", "Loan growth by quarter",
        "Gross loan growth (% YoY)", "loan_growth_trend.png", "{v:.1f}%")


# ---------------------------------------------------------------------------
# Per-bank chart: P/B band
# ---------------------------------------------------------------------------

def _bvps_step_series(ticker: str, index: pd.DatetimeIndex) -> pd.Series:
    """Daily BVPS series: each fiscal year's BVPS becomes effective at its
    Dec-31 fiscal year end (IDX banks are Dec-FYE); earliest value backfills."""
    fund = fetch.fundamentals_frame(ticker)
    knots = pd.Series(
        fund["bvps"].values,
        index=pd.to_datetime([f"{y}-12-31" for y in fund.index]))
    return knots.reindex(index, method="ffill").bfill()


def pb_history(ticker: str, years: int = 5) -> pd.Series:
    px = fetch.load_prices(ticker)["Close"].dropna()
    px = px[px.index >= px.index[-1] - pd.DateOffset(years=years)]
    bvps = _bvps_step_series(ticker, px.index)
    return px / bvps


def chart_pb_band(ticker: str, years: int = 5) -> Path:
    apply_house_style()
    fig, ax = _new_axes()
    pb = pb_history(ticker, years)
    mean, sd = pb.mean(), pb.std()
    info = config.UNIVERSE[ticker]

    ax.plot(pb.index, pb.values, color=info["color"], lw=2.0, zorder=3)
    bands = [(mean + 2 * sd, "+2σ", ":"), (mean + sd, "+1σ", "--"),
             (mean, "5Y mean", "-"), (mean - sd, "−1σ", "--"),
             (mean - 2 * sd, "−2σ", ":")]
    x_end = pb.index[-1]
    span_days = (pb.index[-1] - pb.index[0]).days
    for level, label, style in bands:
        ax.axhline(level, color=INK_MUTED, lw=1.0, ls=style, zorder=2)
        ax.annotate(f"{label}  {level:.1f}x",
                    xy=(mdates.date2num(x_end) + span_days * 0.012, level),
                    fontsize=7.5, color=INK_2, va="center",
                    annotation_clip=False)
    current = float(pb.iloc[-1])
    ax.scatter([pb.index[-1]], [current], s=60, color=info["color"],
               zorder=4, edgecolor="white", linewidth=1.0)
    ax.annotate(f"now {current:.1f}x",
                xy=(mdates.date2num(pb.index[-1]), current),
                xytext=(-8, 10), textcoords="offset points", fontsize=8.5,
                fontweight="bold", color=INK, ha="right")
    z = (current - mean) / sd if sd else float("nan")
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(
        mdates.AutoDateLocator()))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.1f}x"))
    ax.set_xlim(mdates.date2num(pb.index[0]),
                mdates.date2num(pb.index[-1]) + span_days * 0.10)
    _chrome(fig, f"{ticker} — P/B band, {years}-year history",
            f"Price-to-book vs its own history  |  trades {z:+.1f}σ from the "
            f"{years}Y mean ({mean:.1f}x)", _source_line())
    return _save(fig, config.CHART_DIR / ticker / "pb_band.png")


# ---------------------------------------------------------------------------
# Foreign flow exhibits
# ---------------------------------------------------------------------------

def _new_stacked():
    """Two panels sharing the x-axis (house rule: never a dual-axis chart —
    two measures of different scale get two aligned panels)."""
    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, sharex=True, figsize=(9.0, 6.2),
        gridspec_kw={"height_ratios": [3, 2], "hspace": 0.12})
    fig.subplots_adjust(top=0.87, bottom=0.10, left=0.07, right=0.93)
    for ax in (ax_top, ax_bot):
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.grid(False, axis="x")
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0)
    return fig, ax_top, ax_bot


def chart_foreign_flow(ticker: str, years: int = 2) -> Path:
    """Price vs cumulative net foreign flow — the IDX blue-chip exhibit:
    these names trade with foreign money."""
    apply_house_style()
    fig, ax_px, ax_fl = _new_stacked()
    info = config.UNIVERSE[ticker]

    px = fetch.load_prices(ticker)["Close"].dropna()
    flow = flows.flow_series(ticker)
    end = min(px.index[-1], flow.index[-1])
    start = end - pd.DateOffset(years=years)
    px = px[(px.index >= start) & (px.index <= end)]
    cum_tn = flows.cumulative(flow, pd.Timestamp(start)) / 1000.0
    cum_tn = cum_tn[cum_tn.index <= end]

    ax_px.plot(px.index, px.values, color=info["color"], lw=2.0, zorder=3)
    ax_px.set_ylabel("Price (IDR)")
    ax_px.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax_px.annotate(f"{px.iloc[-1]:,.0f}",
                   xy=(mdates.date2num(px.index[-1]), float(px.iloc[-1])),
                   xytext=(6, 0), textcoords="offset points", fontsize=8,
                   fontweight="bold", color=INK, va="center",
                   annotation_clip=False)

    ax_fl.plot(cum_tn.index, cum_tn.values, color=info["color"], lw=2.0,
               zorder=3)
    ax_fl.fill_between(cum_tn.index, 0, cum_tn.values, color=info["color"],
                       alpha=0.12, zorder=2)
    ax_fl.axhline(0, color=SPINE, lw=1.0, zorder=1)
    ax_fl.set_ylabel(f"Cum. net foreign flow\nsince {start:%b %Y} (IDR tn)")
    ax_fl.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+,.0f}"))
    ax_fl.annotate(f"{cum_tn.iloc[-1]:+,.1f} tn",
                   xy=(mdates.date2num(cum_tn.index[-1]),
                       float(cum_tn.iloc[-1])),
                   xytext=(6, 0), textcoords="offset points", fontsize=8,
                   fontweight="bold", color=INK, va="center",
                   annotation_clip=False)
    ax_fl.xaxis.set_major_formatter(mdates.ConciseDateFormatter(
        mdates.AutoDateLocator()))

    c_d = flows.flow_return_correlation(flow, px, 1.0, "D")
    c_w = flows.flow_return_correlation(flow, px, 1.0, "W")
    _chrome(fig, f"{ticker} — price follows foreign money",
            f"Close vs cumulative net foreign buy value  |  trailing-1Y "
            f"corr(flow, return): {c_d:.2f} daily, {c_w:.2f} weekly",
            _source_line() if fetch.any_sample_data() else
            "IDX daily trading summary / broker exports, author calculations")
    return _save(fig, config.CHART_DIR / ticker / "foreign_flow.png")


def chart_foreign_flow_sector(years: int = 1) -> Path:
    """Cumulative net foreign flow, all four banks, common window."""
    apply_house_style()
    fig, ax = _new_axes(legend_room=True)
    series = {t: flows.flow_series(t) for t in config.TICKERS}
    end = max(s.index[-1] for s in series.values())
    start = end - pd.DateOffset(years=years)
    ends: dict[str, tuple[float, float, str]] = {}
    for ticker, flow in series.items():
        cum = flows.cumulative(flow, pd.Timestamp(start)) / 1000.0
        info = config.UNIVERSE[ticker]
        ax.plot(cum.index, cum.values, color=info["color"], lw=2.2,
                label=ticker, marker=info["marker"], markersize=5,
                markevery=max(1, len(cum) // 14), zorder=3)
        ends[ticker] = (mdates.date2num(cum.index[-1]), float(cum.iloc[-1]),
                        f"{ticker} {cum.iloc[-1]:+,.1f}")
    ax.axhline(0, color=SPINE, lw=1.0, zorder=1)
    ax.set_ylabel(f"Cumulative net foreign flow since {start:%b %Y} (IDR tn)")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+,.0f}"))
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(
        mdates.AutoDateLocator()))
    span = mdates.date2num(end) - mdates.date2num(start)
    ax.set_xlim(mdates.date2num(start), mdates.date2num(end) + span * 0.10)
    _end_labels(ax, ends)
    _legend_below(ax)
    _chrome(fig, "Where is foreign money going?",
            f"Cumulative net foreign buy value by bank, trailing "
            f"{12 * years} months (+ = inflow)",
            _source_line() if fetch.any_sample_data() else
            "IDX daily trading summary / broker exports, author calculations")
    return _save(fig, config.CHART_DIR / "sector" / "foreign_flow_cumulative.png")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def generate_all(comps_table: pd.DataFrame | None = None) -> dict[str, Path]:
    """Build every exhibit; returns {name: path} for the report generator."""
    paths: dict[str, Path] = {
        "price_rebased": chart_price_rebased(),
        "roe_vs_pb": chart_roe_pb_scatter(comps_table),
        "nim_trend": chart_nim_trend(),
        "loan_growth_trend": chart_loan_growth_trend(),
        "foreign_flow_sector": chart_foreign_flow_sector(),
    }
    for ticker in config.TICKERS:
        paths[f"pb_band_{ticker}"] = chart_pb_band(ticker)
        paths[f"foreign_flow_{ticker}"] = chart_foreign_flow(ticker)
    return paths


def main() -> int:
    paths = generate_all()
    print("Charts written:")
    for name, path in paths.items():
        print(f"  {name:<22} {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
