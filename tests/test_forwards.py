"""Forward-earnings and consensus-resolution tests."""
import pytest

from src import config, forwards, valuation


class TestConsensusResolution:
    """The source hierarchy: yaml override > cache > none. Consensus is
    never fabricated — absence yields available=False."""

    def test_yaml_override_wins_over_cache(self, monkeypatch):
        monkeypatch.setattr(forwards.fetch, "load_consensus",
                            lambda t: {"target_mean": 9999,
                                       "source": config.SOURCE_YFINANCE})
        a = {"consensus": {"target_price_idr": 5000, "num_analysts": 12,
                           "source": "Bloomberg 2026-07-20"}}
        c = forwards._resolve_consensus("BBRI", a)
        assert c["available"] is True
        assert c["target_mean"] == 5000          # override, not the 9999 cache
        assert c["num_analysts"] == 12
        assert c["source"] == "Bloomberg 2026-07-20"

    def test_cache_used_when_no_override(self, monkeypatch):
        monkeypatch.setattr(forwards.fetch, "load_consensus",
                            lambda t: {"target_mean": 4800, "target_high": 5200,
                                       "target_low": 4300, "num_analysts": 30,
                                       "recommendation_key": "buy",
                                       "consensus_forward_eps": 400,
                                       "source": config.SOURCE_YFINANCE})
        c = forwards._resolve_consensus("BBRI", {"consensus": {}})
        assert c["available"] is True
        assert c["target_mean"] == 4800
        assert c["is_sample"] is False
        assert c["consensus_fwd_eps"] == 400

    def test_sample_cache_is_flagged(self, monkeypatch):
        monkeypatch.setattr(forwards.fetch, "load_consensus",
                            lambda t: {"target_mean": 4800,
                                       "source": config.SOURCE_SAMPLE})
        c = forwards._resolve_consensus("BBRI", {})
        assert c["available"] is True
        assert c["is_sample"] is True

    def test_none_when_no_source(self, monkeypatch):
        monkeypatch.setattr(forwards.fetch, "load_consensus", lambda t: None)
        c = forwards._resolve_consensus("BBRI", {"consensus": {}})
        assert c["available"] is False
        assert c["target_mean"] is None

    def test_null_override_falls_through_to_cache(self, monkeypatch):
        # A consensus block with target_price_idr: null must NOT count as an
        # override — it should fall through to the cache.
        monkeypatch.setattr(forwards.fetch, "load_consensus",
                            lambda t: {"target_mean": 4800,
                                       "source": config.SOURCE_YFINANCE})
        a = {"consensus": {"target_price_idr": None}}
        c = forwards._resolve_consensus("BBRI", a)
        assert c["target_mean"] == 4800
        assert c["source"] == config.SOURCE_YFINANCE


class TestForwardMath:
    """Arithmetic identities that must hold for any bank on any data."""

    @pytest.mark.parametrize("ticker", config.TICKERS)
    def test_forward_pe_identity(self, ticker):
        fv = forwards.forward_view(ticker)
        if fv.fwd_eps_own:
            assert fv.fwd_pe_own == pytest.approx(
                fv.last_close / fv.fwd_eps_own)

    @pytest.mark.parametrize("ticker", config.TICKERS)
    def test_trailing_pe_identity(self, ticker):
        fv = forwards.forward_view(ticker)
        assert fv.trailing_pe == pytest.approx(
            fv.last_close / fv.trailing_eps)

    @pytest.mark.parametrize("ticker", config.TICKERS)
    def test_eps_growth_identity(self, ticker):
        fv = forwards.forward_view(ticker)
        if fv.fwd_eps_own:
            assert fv.eps_growth_pct == pytest.approx(
                100 * (fv.fwd_eps_own / fv.trailing_eps - 1))

    @pytest.mark.parametrize("ticker", config.TICKERS)
    def test_upside_to_target_identity(self, ticker):
        fv = forwards.forward_view(ticker)
        if fv.consensus_available and fv.target_mean:
            assert fv.upside_to_target_pct == pytest.approx(
                100 * (fv.target_mean / fv.last_close - 1))

    @pytest.mark.parametrize("ticker", config.TICKERS)
    def test_model_year1_eps_matches_ri_path(self, ticker):
        """The forward view's model cross-check EPS must equal the residual
        income model's year-1 EPS (same ROE_start x opening book)."""
        fv = forwards.forward_view(ticker)
        val = valuation.value_bank(ticker)
        assert fv.model_year1_eps == pytest.approx(
            float(val.ri_path["eps"].iloc[0]))

    @pytest.mark.parametrize("ticker", config.TICKERS)
    def test_forward_net_income_identity(self, ticker):
        fv = forwards.forward_view(ticker)
        if fv.fwd_eps_own:
            assert fv.fwd_ni_own_tn == pytest.approx(
                fv.fwd_eps_own * fv.shares / 1e12)
