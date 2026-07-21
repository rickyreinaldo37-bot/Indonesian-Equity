# IDX Banks Coverage Engine

A Python research-production system for sell-side-style coverage of the four
Indonesian large-cap banks — **BBCA, BBRI, BMRI, BBNI**. It automates data
collection, comps, valuation, charts, and report scaffolding so the analyst
can focus on thesis, writing, and judgment.

The system deliberately does **not** write the investment thesis, pick
ratings, or generate trading signals — those stay human.

## Quickstart

```bash
pip install -r requirements.txt

python refresh.py                  # 1. fetch/refresh all data (cached locally)
python comps.py                    # 2. build the sector comps workbook (xlsx)
python -m src.valuation BBRI       # 3. print a bank's RI + DDM valuation
python -m src.charts               # 4. render all house-style chart PNGs
python make_report.py BBRI         # 5. generate an initiation report skeleton
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
data/manual/*.csv        analyst-transcribed quarterly bank metrics  ─┐
data/manual/macro.csv    BI rate, USD/IDR, Indonesia 10Y             │ source of
assumptions/*.yaml       valuation inputs, one file per bank         │ truth
data/cache/              yfinance pulls (parquet/json), source-tagged ┘
        │
        ├── src/fetch.py      F1  loaders + schema validation (fails loudly)
        ├── src/comps.py      F2  sector comps → styled Excel workbook
        ├── src/valuation.py  F3  residual income (primary) + DDM cross-check
        ├── src/charts.py     F4  house-style PNG exhibits @300dpi
        └── src/report.py     F5  initiation skeleton (docx / markdown)
```

**Single source of truth:** change one number in
`assumptions/<TICKER>.yaml` (say, terminal ROE) and re-run — fair value,
implied P/B, upside, the sensitivity table, the comps workbook's valuation
block, and the report skeleton all update consistently. No manual edits.

### Outputs

| Command | Output |
|---|---|
| `python comps.py` | `output/comps_YYYY-MM-DD.xlsx` — Summary tab (frozen headers, number formats, conditional formatting vs sector median), one detail tab per bank, Notes tab |
| `python -m src.charts` | `output/charts/sector/` (rebased price, ROE vs P/B with OLS fit, NIM trend, loan growth) and `output/charts/<TICKER>/pb_band.png` (±1σ/±2σ of 5Y history) |
| `python make_report.py <TICKER> [--format md]` | `output/reports/<TICKER>_initiation_skeleton_YYYY-MM-DD.docx` — cover block (rating placeholder, RI price target, upside), thesis/overview/risks placeholders, auto-filled valuation section + sensitivity, embedded exhibits, financials appendix, disclosures |

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

## Quarterly update workflow

1. Results season: add one row per bank to `data/manual/<TICKER>.csv` from
   the investor deck (validation fails loudly on missing/malformed fields).
2. `python refresh.py` — pulls latest prices/fundamentals, revalidates.
3. Revisit `assumptions/<TICKER>.yaml` if the print changes your view.
4. `python comps.py && python -m src.charts` — refreshed exhibits.
5. `python make_report.py <TICKER>` for any report you're writing; fill in
   the qualitative sections.

## Configuration

Analyst name, site, watermark, disclaimer, universe membership, per-bank
house colors/markers: `src/config.py`.

## Repo layout

```
├── refresh.py            # one-command data refresh
├── comps.py              # comps workbook entry point
├── make_report.py        # report skeleton entry point
├── src/                  # engine modules (config, fetch, comps, valuation, charts, report)
├── data/manual/          # analyst-maintained inputs (source of truth)
├── data/cache/           # yfinance cache, source-tagged (sample seed ships here)
├── assumptions/          # per-bank valuation assumptions (yaml)
├── scripts/make_sample_seed.py   # reinstall the offline sample cache
├── tests/                # valuation + schema validation tests
└── output/               # comps xlsx, charts, report skeletons (regenerated)
```

*Everything here is independent research tooling for educational purposes —
not investment advice.*
