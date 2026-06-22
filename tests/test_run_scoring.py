import portfolio_app
from portfolio_app import run_scoring


def test_run_scoring_includes_momentum_signal_field(monkeypatch):
    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (75.0, "High", "Technology", 200.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bullish", "ma50": "bullish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "evaluate_momentum_signal",
                         lambda ticker, score, technicals: "BUY")
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "NVDA", "shares": "10", "invested": "1000", "type": "main"}]
    result = run_scoring(holdings)

    assert result["positions"][0]["momentum_signal"] == "BUY"


def test_run_scoring_includes_watchlisted_since_and_days_until_eligible(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (20.0, "Exit", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bearish", "ma50": "bearish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))
    # Note: evaluate_momentum_signal is NOT mocked here -- the real function must run so it
    # actually calls flag_watchlisted() on this low-score, bearish-confirmed ticker.

    holdings = [{"ticker": "CVNA", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)
    pos = result["positions"][0]

    assert pos["watchlisted_since"] is not None
    assert pos["days_until_eligible"] == 3  # just flagged, full window remains


def test_run_scoring_watchlist_fields_are_none_when_not_flagged(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (75.0, "High", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bullish", "ma50": "bullish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "NVDA", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)
    pos = result["positions"][0]

    assert pos["watchlisted_since"] is None
    assert pos["days_until_eligible"] is None
