"""Valuation math tests against hand-calculated fixtures.

Every expected number below is derived by hand in the comments — no model
output was pasted back in as an expectation.
"""
import numpy as np
import pandas as pd
import pytest

from src.valuation import (
    AssumptionsError,
    ValuationError,
    capm_coe,
    ddm_value,
    residual_income_value,
    roe_fade_path,
    sensitivity_table,
)


class TestCAPM:
    def test_capm(self):
        # 6.5 + 1.2 × 5.0 = 12.5
        a = {"cost_of_equity": {"risk_free_pct": 6.5,
                                "equity_risk_premium_pct": 5.0,
                                "beta": 1.2, "coe_override_pct": None}}
        assert capm_coe(a) == pytest.approx(12.5)

    def test_override_wins(self):
        a = {"cost_of_equity": {"risk_free_pct": 6.5,
                                "equity_risk_premium_pct": 5.0,
                                "beta": 1.2, "coe_override_pct": 10.0}}
        assert capm_coe(a) == pytest.approx(10.0)


class TestRoeFade:
    def test_linear_path(self):
        # 20 → 12 over 5 years: 20, 18, 16, 14, 12
        assert roe_fade_path(20, 12, 5) == pytest.approx([20, 18, 16, 14, 12])

    def test_single_year_is_terminal(self):
        assert roe_fade_path(20, 12, 1) == pytest.approx([12])

    def test_rising_path_allowed(self):
        # Recovery stories fade upward: 16 → 17 over 3 years
        assert roe_fade_path(16, 17, 3) == pytest.approx([16, 16.5, 17])


class TestResidualIncomeHandCalc:
    def test_constant_roe_matches_gordon(self):
        """Constant ROE 15%, COE 10%, g 5%, payout = 1 − g/ROE = 2/3.

        Book grows exactly at g every year, so RI_1 = (15% − 10%) × 1000 = 50
        and the whole stream is a growing perpetuity:
            FV = BV0 + RI_1 / (COE − g) = 1000 + 50 / 0.05 = 2000.
        The horizon split (5 explicit years + terminal) must not change it.
        """
        fv, path, terminal = residual_income_value(
            bvps_0=1000, coe_pct=10,
            roe_path_pct=[15] * 5,
            payout_pct=100 * (1 - 0.05 / 0.15),  # 66.667%
            terminal_growth_pct=5)
        assert fv == pytest.approx(2000, rel=1e-9)
        # Justified terminal P/B = (ROE − g)/(COE − g) = 10/5 = 2.0
        assert terminal["justified_terminal_pb"] == pytest.approx(2.0)
        # Book must compound at exactly g = 5%
        assert path["bvps_close"].iloc[0] == pytest.approx(1050)
        assert path["bvps_close"].iloc[-1] == pytest.approx(
            1000 * 1.05 ** 5)

    def test_two_year_fade_hand_calc(self):
        """BV0 1000, COE 10%, ROE 20% → 12% over 2 years, payout 50%, g 4%.

        Year 1: EPS = 200, DPS = 100, BV → 1100, RI = 200 − 100 = 100,
                PV = 100 / 1.1 = 90.909091
        Year 2: EPS = 0.12 × 1100 = 132, DPS = 66, BV → 1166,
                RI = 132 − 110 = 22, PV = 22 / 1.21 = 18.181818
        Terminal: payout* = 1 − 0.04/0.12 = 2/3
                EPS_3 = 0.12 × 1166 = 139.92
                RI_3 = 139.92 − 0.10 × 1166 = 23.32
                TV = 23.32 / (0.10 − 0.04) = 388.666667
                PV(TV) = 388.666667 / 1.21 = 321.212121
        FV = 1000 + 90.909091 + 18.181818 + 321.212121 = 1430.303030
        """
        fv, path, _ = residual_income_value(
            bvps_0=1000, coe_pct=10, roe_path_pct=[20, 12],
            payout_pct=50, terminal_growth_pct=4)
        assert path["eps"].tolist() == pytest.approx([200, 132])
        assert path["dps"].tolist() == pytest.approx([100, 66])
        assert path["ri"].tolist() == pytest.approx([100, 22])
        assert path["pv_ri"].tolist() == pytest.approx(
            [90.90909091, 18.18181818], rel=1e-8)
        assert fv == pytest.approx(1430.303030, rel=1e-9)

    def test_roe_equal_to_coe_adds_nothing(self):
        """ROE == COE forever → zero residual income → FV = book value."""
        fv, _, _ = residual_income_value(
            bvps_0=1000, coe_pct=12, roe_path_pct=[12, 12, 12],
            payout_pct=100 * (1 - 0.04 / 0.12), terminal_growth_pct=4)
        assert fv == pytest.approx(1000, rel=1e-9)


class TestDDMHandCalc:
    def test_two_year_hand_calc(self):
        """Same fixture as the RI two-year test, valued through dividends.

        PV(DPS_1) = 100 / 1.1 = 90.909091
        PV(DPS_2) = 66 / 1.21 = 54.545455
        DPS_3 = EPS_3 × payout* = 139.92 × 2/3 = 93.28
        TV = 93.28 / 0.06 = 1554.666667 ; PV = 1554.666667/1.21 = 1284.848485
        FV = 90.909091 + 54.545455 + 1284.848485 = 1430.303030
        """
        fv, _ = ddm_value(bvps_0=1000, coe_pct=10, roe_path_pct=[20, 12],
                          payout_pct=50, terminal_growth_pct=4)
        assert fv == pytest.approx(1430.303030, rel=1e-9)

    def test_gordon_constant_state(self):
        """Constant ROE 15%, payout 2/3 → DPS_1 = 100 growing at 5%:
        FV = 100 / (0.10 − 0.05) = 2000."""
        fv, _ = ddm_value(bvps_0=1000, coe_pct=10, roe_path_pct=[15] * 4,
                          payout_pct=100 * (1 - 0.05 / 0.15),
                          terminal_growth_pct=5)
        assert fv == pytest.approx(2000, rel=1e-9)


class TestModelConsistency:
    def test_ri_equals_ddm_under_clean_surplus(self):
        """Under clean surplus with a sustainable-growth terminal payout the
        two models are algebraically identical for ANY horizon payout,
        fade shape, or horizon length."""
        cases = [
            dict(bvps_0=1000, coe_pct=10, roe_path_pct=[20, 12],
                 payout_pct=50, terminal_growth_pct=4),
            dict(bvps_0=2217, coe_pct=11.4, roe_path_pct=[16, 16.5, 17],
                 payout_pct=80, terminal_growth_pct=5),
            dict(bvps_0=500, coe_pct=14, roe_path_pct=[25, 22, 19, 16, 13],
                 payout_pct=30, terminal_growth_pct=6),
        ]
        for kw in cases:
            fv_ri, _, _ = residual_income_value(**kw)
            fv_ddm, _ = ddm_value(**kw)
            assert fv_ri == pytest.approx(fv_ddm, rel=1e-10), kw


class TestSensitivity:
    def test_grid_shape_center_and_monotonicity(self):
        base_fv, _, _ = residual_income_value(
            bvps_0=1000, coe_pct=10, roe_path_pct=roe_fade_path(20, 15, 5),
            payout_pct=60, terminal_growth_pct=4)
        tbl = sensitivity_table(
            bvps_0=1000, coe_pct=10, roe_terminal_pct=15, roe_start_pct=20,
            years=5, payout_pct=60, terminal_growth_pct=4)
        assert tbl.shape == (5, 5)
        # Center cell equals the base-case fair value
        assert tbl.iloc[2, 2] == pytest.approx(base_fv, rel=1e-12)
        # Fair value falls as COE rises (down each column) …
        for col in tbl.columns:
            assert tbl[col].is_monotonic_decreasing
        # … and rises with terminal ROE (across each row)
        for _, row in tbl.iterrows():
            assert row.is_monotonic_increasing


class TestValidation:
    def test_coe_must_exceed_growth(self):
        with pytest.raises(ValuationError, match="exceed terminal growth"):
            residual_income_value(1000, 5, [15, 15], 60, 6)

    def test_terminal_roe_must_exceed_growth(self):
        with pytest.raises(ValuationError, match="Terminal ROE"):
            residual_income_value(1000, 12, [15, 3], 60, 4)

    def test_forecast_years_positive(self):
        with pytest.raises(ValuationError, match="forecast_years"):
            roe_fade_path(20, 15, 0)


class TestAssumptionsSchema:
    def test_missing_key_fails_loudly(self, tmp_path, monkeypatch):
        from src import config as cfg
        from src import valuation as val
        broken = tmp_path / "BBCA.yaml"
        broken.write_text(
            "ticker: BBCA\n"
            "cost_of_equity:\n  risk_free_pct: 6.4\n  beta: 0.9\n"
            "residual_income:\n  forecast_years: 5\n")
        monkeypatch.setattr(cfg, "ASSUMPTIONS_DIR", tmp_path)
        with pytest.raises(AssumptionsError) as err:
            val.load_assumptions("BBCA")
        msg = str(err.value)
        assert "equity_risk_premium_pct" in msg
        assert "roe_start_pct" in msg

    def test_payout_range_enforced(self, tmp_path, monkeypatch):
        from src import config as cfg
        from src import valuation as val
        bad = tmp_path / "BBCA.yaml"
        bad.write_text(
            "ticker: BBCA\n"
            "cost_of_equity:\n  risk_free_pct: 6.4\n"
            "  equity_risk_premium_pct: 5.0\n  beta: 0.9\n"
            "residual_income:\n  forecast_years: 5\n  roe_start_pct: 20\n"
            "  roe_terminal_pct: 18\n  payout_ratio_pct: 130\n"
            "  terminal_growth_pct: 4\n")
        monkeypatch.setattr(cfg, "ASSUMPTIONS_DIR", tmp_path)
        with pytest.raises(AssumptionsError, match="payout_ratio_pct"):
            val.load_assumptions("BBCA")


class TestManualSchema:
    def test_missing_column_fails_loudly(self, tmp_path, monkeypatch):
        from src import config as cfg
        from src import fetch
        bad = tmp_path / "BBCA.csv"
        bad.write_text("period,period_end,nim_pct\n2025Q1,2025-03-31,5.5\n")
        monkeypatch.setattr(cfg, "MANUAL_DIR", tmp_path)
        with pytest.raises(fetch.ManualDataError) as err:
            fetch.load_manual_metrics("BBCA")
        assert "casa_pct" in str(err.value)
        assert "npl_pct" in str(err.value)

    def test_non_numeric_value_fails_loudly(self, tmp_path, monkeypatch):
        from src import config as cfg
        from src import fetch
        header = ",".join(fetch.MANUAL_REQUIRED_COLUMNS)
        bad = tmp_path / "BBCA.csv"
        bad.write_text(header + "\n"
                       "2025Q1,2025-03-31,5.5,81,abc,29,12,0.4,34,src\n")
        monkeypatch.setattr(cfg, "MANUAL_DIR", tmp_path)
        with pytest.raises(fetch.ManualDataError, match="npl_pct"):
            fetch.load_manual_metrics("BBCA")
