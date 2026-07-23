"""Tests for the offline price & fundamentals CSV import layer."""
import pytest

from src import config, fetch


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

class TestManualPriceImport:
    def test_yahoo_format(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            "Date,Open,High,Low,Close,Adj Close,Volume\n"
            "2026-07-16,9375,9425,9350,9400,9400,80300000\n"
            "2026-07-17,9400,9450,9375,9425,9425,59900000\n")
        df = fetch._load_manual_prices_csv("BBCA")
        assert list(df.columns) == ["Open", "High", "Low", "Close",
                                    "AdjClose", "Volume"]
        assert df["Close"].tolist() == [9400, 9425]
        assert str(df.index[0].date()) == "2026-07-16"

    def test_tradingview_lowercase_backfills_ohlc(self, tmp_path, monkeypatch):
        # Only time + close-ish columns; OHLC/AdjClose/Volume must backfill.
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBRI.csv").write_text(
            "time,close\n2026-07-16,4380\n2026-07-17,4400\n")
        df = fetch._load_manual_prices_csv("BBRI")
        assert df["Open"].tolist() == [4380, 4400]      # backfilled from close
        assert df["AdjClose"].tolist() == [4380, 4400]
        assert df["Volume"].tolist() == [0.0, 0.0]

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        assert fetch._load_manual_prices_csv("BBCA") is None

    def test_no_close_column_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text("Date,Open,High\n2026-07-16,1,2\n")
        with pytest.raises(fetch.ManualDataError, match="close price"):
            fetch._load_manual_prices_csv("BBCA")

    def test_no_date_column_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text("Close\n9400\n")
        with pytest.raises(fetch.ManualDataError, match="date column"):
            fetch._load_manual_prices_csv("BBCA")

    def test_unparseable_date_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            "Date,Close\nnot-a-date,9400\n")
        with pytest.raises(fetch.ManualDataError, match="unparseable date"):
            fetch._load_manual_prices_csv("BBCA")

    def test_yahoo_null_rows_dropped(self, tmp_path, monkeypatch):
        # Yahoo sometimes emits 'null' on non-trading rows.
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            "Date,Close\n2026-07-16,9400\n2026-07-17,null\n"
            "2026-07-20,9410\n")
        df = fetch._load_manual_prices_csv("BBCA")
        assert df["Close"].tolist() == [9400, 9410]

    def test_non_positive_close_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text("Date,Close\n2026-07-16,0\n")
        with pytest.raises(fetch.ManualDataError, match="non-positive"):
            fetch._load_manual_prices_csv("BBCA")

    def test_duplicate_dates_last_wins_and_sorted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_PRICE_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            "Date,Close\n2026-07-17,9425\n2026-07-16,9400\n"
            "2026-07-17,9430\n")
        df = fetch._load_manual_prices_csv("BBCA")
        assert df.index.is_monotonic_increasing
        assert df.loc["2026-07-17", "Close"] == 9430   # last duplicate wins


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------

class TestManualFundamentalsImport:
    HEADER = ("fiscal_year,net_income_idr_bn,total_equity_idr_bn,"
              "total_assets_idr_bn,shares_bn,dps_idr,source\n")

    def test_import_and_derived_per_share(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_FUND_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            self.HEADER +
            "2024,54800,262000,1450000,123.275,300,FY24 report\n"
            "2025,57500,281000,1540000,123.275,315,FY25 report\n")
        data = fetch._load_manual_fundamentals_csv("BBCA")
        assert data["source"] == config.SOURCE_MANUAL_CSV
        assert set(data["annual"]) == {"2024", "2025"}
        a25 = data["annual"]["2025"]
        # net income 57,500 bn absolute, shares 123.275 bn absolute
        assert a25["net_income"] == pytest.approx(57500e9)
        assert a25["eps"] == pytest.approx(57500 / 123.275, rel=1e-9)
        assert a25["bvps"] == pytest.approx(281000 / 123.275, rel=1e-9)
        assert a25["dps"] == 315
        assert data["shares_outstanding"] == pytest.approx(123.275e9)

    def test_missing_column_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_FUND_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            "fiscal_year,net_income_idr_bn,source\n2025,57500,x\n")
        with pytest.raises(fetch.ManualDataError, match="total_equity_idr_bn"):
            fetch._load_manual_fundamentals_csv("BBCA")

    def test_non_numeric_value_fails_loudly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_FUND_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            self.HEADER + "2025,abc,281000,1540000,123.275,315,x\n")
        with pytest.raises(fetch.ManualDataError, match="net_income_idr_bn"):
            fetch._load_manual_fundamentals_csv("BBCA")

    def test_non_positive_shares_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_FUND_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            self.HEADER + "2025,57500,281000,1540000,0,315,x\n")
        with pytest.raises(fetch.ManualDataError, match="must be positive"):
            fetch._load_manual_fundamentals_csv("BBCA")

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_FUND_DIR", tmp_path)
        assert fetch._load_manual_fundamentals_csv("BBCA") is None

    def test_rows_sorted_by_year(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "MANUAL_FUND_DIR", tmp_path)
        (tmp_path / "BBCA.csv").write_text(
            self.HEADER +
            "2025,57500,281000,1540000,123.275,315,x\n"
            "2024,54800,262000,1450000,123.275,300,x\n")
        data = fetch._load_manual_fundamentals_csv("BBCA")
        assert list(data["annual"]) == ["2024", "2025"]
        # shares_outstanding taken from the latest fiscal year
        assert data["shares_outstanding"] == pytest.approx(123.275e9)
