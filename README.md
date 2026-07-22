# IDX Banks Coverage Engine

A Python research-production system for sell-side-style coverage of the four
Indonesian large-cap banks — **BBCA, BBRI, BMRI, BBNI**. It automates data
collection, comps, valuation, **forward earnings & consensus**, charts,
**net foreign flow monitoring**, and report scaffolding so the analyst can
focus on thesis, writing, and judgment.

The system deliberately does **not** write the investment thesis, pick
ratings, or generate trading signals — those stay human.

## Quickstart

```bash
pip install -r requirements.txt

python refresh.py                  # 1. fetch/refresh all data (cached locally)
python comps.py                    # 2. build the sector comps workbook (xlsx)
python -m src.valuation BBRI       # 3. print a bank's RI + DDM valuation
python -m src.forwards BBRI        # 4. print forward EPS, forward P/E, consensus
python -m src.charts               # 5. render all house-style chart PNGs
python make_report.py BBRI         # 6. generate an initiation report skeleton
```

`python refresh.py && python comps.py` produces the styled workbook
`output/comps_YYYY-MM-DD.xlsx` end-to-end (well under two minutes).

## ⚠ Sample data mode (read this first)

The repo ships with a **SAMPLE placeholder cache** so everything runs
offline out of the box. Sample figures are *illustrative approximations,
not real market data*. Every file in `data/cache/` carries a `source` tag
(`SAMPLE_SEED` vs `yfinance`), and every output — Excel, charts, reports —
displays a red **SAMPLE DATA** banner until all inputs are live.

To go live:

1. Run `python refresh.py --force` on a machine with internet access —
   prices and fundamentals are re-pulled from Yahoo Finance and the source
   tags flip to `yfinance` automatically.
2. Transcribe real quarterly metrics (NIM, CASA, NPL, CAR, loan growth,
   cost of credit, cost/income) from each bank's investor presentation into
   `data/manual/<TICKER>.csv`, replacing the `SAMPLE — …` source labels
   with your citation (e.g. `BBRI 1Q26 analyst deck p.12`).
3. Review every number in `assumptions/<TICKER>.yaml` — betas, ERP,
   ROE fade paths, payout, terminal growth, and your own forward EPS
   estimates.

The banners disappear only when nothing sample-tagged remains.

## How it fits together

```
data/manual/*.csv               analyst-transcribed quarterly bank metrics ─┐
data/manual/foreign_flow/*.csv  net foreign flow export (optional)          │ source
data/manual/macro.csv           BI rate, USD/IDR, Indonesia 10Y             │ of
assumptions/*.yaml              valuation inputs, one file per bank         │ truth
data/cache/                     yfinance + flow pulls, source-tagged        ┘
        │
        ├── src/fetch.py      F1  loaders + schema validation (fails loudly)
        ├── src/comps.py      F2  sector comps → styled Excel workbook
        ├── src/valuation.py  F3  residual income (primary) + DDM cross-check
        ├── src/charts.py     F4  house-style PNG exhibits @300dpi
        ├── src/flows.py          net foreign flow analytics (sums, corr)
        ├── src/forwards.py       forward EPS / forward P/E / consensus
        └── src/report.py     F5  initiation skeleton (docx / markdown)
```

**Single source of truth:** change one number in
`assumptions/<TICKER>.yaml` (say, terminal ROE) and re-run — fair value,
implied P/B, upside, the sensitivity table, the comps workbook's valuation
block, and the report skeleton all update consistently. No manual edits.

### Outputs

| Command | Output |
|---|---|
| `python comps.py` | `output/comps_YYYY-MM-DD.xlsx` — Summary tab (frozen headers, number formats, conditional formatting vs sector median, on 3M net foreign flow **and on upside-to-consensus-target**; forward P/E + **consensus target/upside columns**), one detail tab per bank (incl. **forward-estimates & consensus block** and a foreign-flow monitor block), Notes tab |
| `python -m src.forwards <TICKER>` | Prints 12M forward EPS (own est.), forward net income, EPS growth, forward P/E, model cross-check, and consensus target/upside/rating (real source or n/a) |
| `python -m src.charts` | `output/charts/sector/` (rebased price, ROE vs P/B with OLS fit, NIM trend, loan growth, **cumulative net foreign flow by bank**) and `output/charts/<TICKER>/` (`pb_band.png` ±1σ/±2σ of 5Y history, **`foreign_flow.png` price vs cumulative flow**) |
| `python make_report.py <TICKER> [--format md]` | `output/reports/<TICKER>_initiation_skeleton_YYYY-MM-DD.docx` — cover block (rating placeholder, RI price target, **consensus target**, upside), thesis/overview/risks placeholders, auto-filled valuation section + sensitivity, **earnings forecast & forward valuation** (forward P/E + consensus), **foreign flow monitor**, embedded exhibits, financials appendix, disclosures |

## Valuation methodology

- **Residual income (primary)** — appropriate for banks:
  `FV = BVPS₀ + Σ PV[(ROEₜ − COE) × BVPSₜ₋₁] + PV(terminal RI)`.
  ROE fades linearly to the terminal level; book compounds under clean
  surplus; terminal residual income grows at `g` with the
  sustainable-growth payout `1 − g/ROE_terminal`.
- **DDM cross-check** — same forecast path valued through dividends. With a
  sustainable-growth terminal payout the two models are algebraically
  identical; the unit tests assert this to 1e-10.
- **Cost of equity** — CAPM with Indonesia inputs (`rf + β × ERP`) or an
  explicit override.
- **Sensitivity** — fair-value grid over COE (±1.0pp) × terminal ROE (±2pp).

Run the math tests (hand-calculated fixtures, documented in-line):

```bash
python -m pytest tests/ -q
```

## Forward earnings & consensus

The engine keeps two forward-looking things strictly separate and clearly
labeled — it never presents one as the other:

**1. Your own 12-month forward view.** Forward EPS is *your* FY+1 estimate,
set in `assumptions/<TICKER>.yaml` (`forward_eps`) — there is no consensus
feed behind it. From it the engine derives forward net income, YoY earnings
growth, and **forward P/E** (last close ÷ forward EPS), and cross-checks it
against the residual income model's own year-1 implied EPS
(ROE-start × opening book). A wide gap flags an estimate to revisit.

**2. Sell-side consensus.** Target price, analyst count, rating, and
consensus forward EPS come from a **real source only**:

1. An analyst-sourced override in `assumptions/<TICKER>.yaml` (`consensus`
   block) — paste a figure you sourced and cite it. Highest priority.
2. The yfinance consensus cache (`targetMeanPrice`, `numberOfAnalystOpinions`,
   `recommendationKey`, `forwardEps`), refreshed by `refresh.py`.
3. If neither exists, **every consensus field is reported as `n/a`**.

**Consensus is never fabricated.** Offline, the repo ships clearly-tagged
`SAMPLE` placeholders (so the report's forward section has structure to
show); they are labeled "SAMPLE — illustrative, NOT real consensus" and are
replaced by real aggregated targets on a live yfinance refresh.

This surfaces in the report cover block (house RI target *and* consensus
target side by side), a dedicated "Earnings forecast & forward valuation"
section, and the comps workbook (forward P/E, consensus target, upside-to-
target columns + a per-bank forward block). See `src/forwards.py`
(`python -m src.forwards <TICKER>`).

## Net foreign flow

Indonesian blue chips — the big four banks especially — trade with foreign
positioning: cumulative net foreign flow tracks their price cycles closely.
The engine treats daily net foreign flow (net foreign buy value, IDR bn) as
a first-class input.

**Source hierarchy** (highest priority wins, mirroring the rest of the
engine):

1. `data/manual/foreign_flow/<TICKER>.csv` — an analyst-exported series
   from a broker terminal, RTI, Stockbit, or the IDX daily trading summary.
   If present it is the source of truth. Columns: `date`, `source`, and
   either `net_foreign_idr_bn` **or** `foreign_buy_idr_bn` +
   `foreign_sell_idr_bn` (net is derived). Values are IDR **billions**; a
   loud unit sanity-check rejects anything above ±20,000 bn/day.
2. A best-effort pull of recent days from the IDX daily trading summary
   endpoint (unofficial; convenience only — parsed values are
   sanity-checked and only fill dates missing from the cache).
3. The existing cache (including the shipped SAMPLE seed).

**What it produces:**

- Horizon sums (1W / 1M / 3M / 6M / YTD / 12M) per bank, in the comps
  Summary tab (with conditional formatting), each bank's detail tab, and the
  report's foreign flow monitor section.
- Flow/return correlation — Pearson(daily net flow, daily return) over the
  trailing year, daily and weekly. This is **contemporaneous co-movement, a
  diagnostic — not a predictive signal**, and every output labels it as such.
- Two exhibits: per-bank price vs cumulative flow (stacked panels, never a
  dual-axis chart), and a sector cumulative-flow comparison.

Analytics live in `src/flows.py` (pure functions, unit-tested against hand
fixtures); the flow cache and CSV/IDX import live in `src/fetch.py`.

## Quarterly update workflow

1. Results season: add one row per bank to `data/manual/<TICKER>.csv` from
   the investor deck (validation fails loudly on missing/malformed fields).
2. Drop your latest net-foreign-flow export into
   `data/manual/foreign_flow/<TICKER>.csv` (optional but recommended for
   real data — otherwise the engine tries the IDX endpoint, then the cache).
3. `python refresh.py` — pulls prices/fundamentals/flow/consensus, revalidates.
4. Revisit `assumptions/<TICKER>.yaml` if the print changes your view —
   including `forward_eps` (your FY+1 estimate) and the optional `consensus`
   override block.
5. `python comps.py && python -m src.charts` — refreshed exhibits.
6. `python make_report.py <TICKER>` for any report you're writing; fill in
   the qualitative sections.

## Configuration

Analyst name, site, watermark, disclaimer, universe membership, per-bank
house colors/markers: `src/config.py`.

## Repo layout

```
├── refresh.py            # one-command data refresh
├── comps.py              # comps workbook entry point
├── make_report.py        # report skeleton entry point
├── src/                  # engine modules (config, fetch, comps, valuation, charts, flows, forwards, report)
├── data/manual/          # analyst-maintained inputs (source of truth)
│   └── foreign_flow/     # optional net-foreign-flow CSV exports per bank
├── data/cache/           # yfinance + flow + consensus cache, source-tagged (sample seed ships here)
├── assumptions/          # per-bank valuation assumptions (yaml)
├── scripts/make_sample_seed.py   # reinstall the offline sample cache
├── tests/                # valuation + schema validation tests
└── output/               # comps xlsx, charts, report skeletons (regenerated)
```

*Everything here is independent research tooling for educational purposes —
not investment advice.*
