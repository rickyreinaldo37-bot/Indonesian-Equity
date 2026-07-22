"""Central configuration for the IDX Banks Coverage Engine.

Everything that identifies the analyst, the coverage universe, and where
files live sits here so the rest of the codebase never hard-codes paths
or tickers.
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Analyst identity (edit these — they appear on charts and reports)
# ---------------------------------------------------------------------------
ANALYST_NAME = "Ricky Reinaldo"
SITE_NAME = "Indonesian Equity Research"
WATERMARK = f"{ANALYST_NAME} | {SITE_NAME}"
DISCLAIMER = (
    "This material is independent research prepared for educational purposes. "
    "It is not investment advice, an offer, or a solicitation to buy or sell "
    "any security. Figures may contain errors; verify against primary filings."
)

# ---------------------------------------------------------------------------
# Coverage universe
# ---------------------------------------------------------------------------
# House colors: one fixed color per bank so every chart in every report uses
# the same encoding. Order here is the canonical display order. The four hues
# are a CVD-validated categorical sequence (adjacent-pair colorblind
# separation + lightness/chroma gates); each bank also owns a fixed marker
# shape as a color-independent secondary encoding for print/grayscale.
UNIVERSE: dict[str, dict] = {
    "BBCA": {
        "name": "PT Bank Central Asia Tbk",
        "short": "Bank Central Asia",
        "yf": "BBCA.JK",
        "color": "#2a78d6",  # blue
        "marker": "o",
    },
    "BBRI": {
        "name": "PT Bank Rakyat Indonesia (Persero) Tbk",
        "short": "Bank Rakyat Indonesia",
        "yf": "BBRI.JK",
        "color": "#eb6834",  # orange
        "marker": "s",
    },
    "BMRI": {
        "name": "PT Bank Mandiri (Persero) Tbk",
        "short": "Bank Mandiri",
        "yf": "BMRI.JK",
        "color": "#1baf7a",  # aqua-green
        "marker": "^",
    },
    "BBNI": {
        "name": "PT Bank Negara Indonesia (Persero) Tbk",
        "short": "Bank Negara Indonesia",
        "yf": "BBNI.JK",
        "color": "#eda100",  # yellow-gold
        "marker": "D",
    },
}
TICKERS = list(UNIVERSE)

# Daily price history start date for fetches and P/B band windows.
PRICE_START = "2019-01-01"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
PRICE_CACHE_DIR = CACHE_DIR / "prices"
FUND_CACHE_DIR = CACHE_DIR / "fundamentals"
FLOW_CACHE_DIR = CACHE_DIR / "foreign_flow"
MANUAL_DIR = DATA_DIR / "manual"
MANUAL_FLOW_DIR = MANUAL_DIR / "foreign_flow"
ASSUMPTIONS_DIR = ROOT / "assumptions"
OUTPUT_DIR = ROOT / "output"
CHART_DIR = OUTPUT_DIR / "charts"
REPORT_DIR = OUTPUT_DIR / "reports"

for _d in (PRICE_CACHE_DIR, FUND_CACHE_DIR, FLOW_CACHE_DIR, MANUAL_DIR,
           MANUAL_FLOW_DIR, ASSUMPTIONS_DIR, CHART_DIR, REPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Data-source tags stored in cache metadata. SAMPLE_SEED marks illustrative
# placeholder data shipped with the repo; a successful refresh from a live
# source overwrites it and re-tags the cache accordingly.
SOURCE_YFINANCE = "yfinance"
SOURCE_IDX = "idx.co.id"
SOURCE_MANUAL_CSV = "manual_csv"
SOURCE_SAMPLE = "SAMPLE_SEED"
