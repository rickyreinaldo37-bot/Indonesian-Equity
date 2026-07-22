"""Foreign-flow analytics tests against hand-built fixtures."""
import numpy as np
import pandas as pd
import pytest

from src.flows import (
    cumulative,
    flow_return_correlation,
    horizon_table,
    window_sum,
    ytd_sum,
)


def _ten_days() -> pd.Series:
    """Business days 2026-01-05 … 2026-01-16 with flows 1..10."""
    idx = pd.bdate_range("2026-01-05", "2026-01-16")
    assert len(idx) == 10
    return pd.Series(range(1, 11), index=idx, dtype=float)


class TestWindows:
    def test_one_week_window(self):
        # Last date Fri 2026-01-16; > 2026-01-09 keeps Mon 12th..Fri 16th:
        # 6+7+8+9+10 = 40
        assert window_sum(_ten_days(), 7) == pytest.approx(40)

    def test_full_window(self):
        # 30 days covers everything: 1+2+…+10 = 55
        assert window_sum(_ten_days(), 30) == pytest.approx(55)

    def test_ytd_excludes_prior_year(self):
        flow = pd.concat([
            pd.Series([100.0], index=[pd.Timestamp("2025-12-31")]),
            _ten_days(),
        ])
        assert ytd_sum(flow) == pytest.approx(55)
        assert window_sum(flow, 365) == pytest.approx(155)

    def test_horizon_table_keys_and_values(self):
        tbl = horizon_table(_ten_days())
        assert list(tbl.index) == ["1W", "1M", "3M", "6M", "12M", "YTD"]
        assert tbl["1W"] == pytest.approx(40)
        assert tbl["1M"] == pytest.approx(55)

    def test_cumulative_from_start(self):
        flow = _ten_days()
        assert cumulative(flow).iloc[-1] == pytest.approx(55)
        # Starting Mon 12th keeps 6..10 → ends at 40
        cut = cumulative(flow, pd.Timestamp("2026-01-12"))
        assert cut.iloc[0] == pytest.approx(6)
        assert cut.iloc[-1] == pytest.approx(40)

    def test_empty_series_is_nan(self):
        empty = pd.Series(dtype=float)
        assert np.isnan(window_sum(empty, 7))
        assert np.isnan(ytd_sum(empty))


def _price_and_flow(k: float = 500.0):
    """Deterministic returns; flow is an exact linear function of the
    same-day return, so daily correlation must be exactly ±1. 60 business
    days = 12 weeks (clears the weekly minimum-sample guard); each week is
    scaled differently so the weekly aggregates are not a constant series."""
    idx = pd.bdate_range("2026-01-05", periods=60)
    base = [0.01, -0.005, 0.003, 0.007, -0.012]
    vals = [r * (1.0 + 0.15 * w) for w in range(12) for r in base]
    ret = pd.Series(vals, index=idx)
    close = 100 * (1 + ret).cumprod()
    flow = k * ret
    return close, flow


class TestCorrelation:
    def test_perfectly_correlated_flow(self):
        close, flow = _price_and_flow(k=500.0)
        corr = flow_return_correlation(flow, close, years=1.0, freq="D")
        assert corr == pytest.approx(1.0, abs=1e-9)

    def test_perfectly_anticorrelated_flow(self):
        close, flow = _price_and_flow(k=-500.0)
        corr = flow_return_correlation(flow, close, years=1.0, freq="D")
        assert corr == pytest.approx(-1.0, abs=1e-9)

    def test_alignment_inner_join(self):
        # Dropping every 5th flow observation must not break the join or
        # the perfect correlation of the surviving pairs.
        close, flow = _price_and_flow()
        flow = flow[[i % 5 != 0 for i in range(len(flow))]]
        corr = flow_return_correlation(flow, close, years=1.0, freq="D")
        assert corr == pytest.approx(1.0, abs=1e-9)

    def test_weekly_aggregation_near_perfect(self):
        # Weekly sums of flow vs compounded weekly returns: linear only to
        # first order, so near-1 rather than exactly 1.
        close, flow = _price_and_flow()
        corr = flow_return_correlation(flow, close, years=1.0, freq="W")
        assert corr > 0.99

    def test_too_few_points_is_nan(self):
        idx = pd.bdate_range("2026-01-05", periods=4)
        close = pd.Series([100, 101, 102, 103.0], index=idx)
        flow = pd.Series([1, 2, 3, 4.0], index=idx)
        assert np.isnan(flow_return_correlation(flow, close))


class TestManualFlowCsv:
    def test_missing_columns_fail_loudly(self, tmp_path, monkeypatch):
        from src import config as cfg
        from src import fetch
        (tmp_path / "BBCA.csv").write_text("date,foo\n2026-01-05,1\n")
        monkeypatch.setattr(cfg, "MANUAL_FLOW_DIR", tmp_path)
        with pytest.raises(fetch.ManualDataError, match="net_foreign_idr_bn"):
            fetch._load_manual_flow_csv("BBCA")

    def test_net_derived_from_buy_sell_legs(self, tmp_path, monkeypatch):
        from src import config as cfg
        from src import fetch
        (tmp_path / "BBCA.csv").write_text(
            "date,foreign_buy_idr_bn,foreign_sell_idr_bn,source\n"
            "2026-01-05,500,320,broker export\n"
            "2026-01-06,410,530,broker export\n")
        monkeypatch.setattr(cfg, "MANUAL_FLOW_DIR", tmp_path)
        df = fetch._load_manual_flow_csv("BBCA")
        assert df["net_foreign_idr_bn"].tolist() == pytest.approx([180, -120])

    def test_unit_sanity_check(self, tmp_path, monkeypatch):
        # A day showing IDR 500,000 bn (= 500 tn) is clearly a unit mistake
        from src import config as cfg
        from src import fetch
        (tmp_path / "BBCA.csv").write_text(
            "date,net_foreign_idr_bn,source\n2026-01-05,500000,oops\n")
        monkeypatch.setattr(cfg, "MANUAL_FLOW_DIR", tmp_path)
        with pytest.raises(fetch.ManualDataError, match="check units"):
            fetch._load_manual_flow_csv("BBCA")
