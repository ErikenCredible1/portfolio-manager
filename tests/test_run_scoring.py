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


def test_run_scoring_days_until_eligible_stays_none_when_mixed_with_watchlisted_rows(monkeypatch, tmp_path):
    # Regression test: pandas upcasts an int/None DataFrame column to float64 when rows mix
    # the two, turning None into NaN. A portfolio with one watchlisted and one clean position
    # is exactly the case that exposes this -- a single-row portfolio never hits it.
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))

    def fake_score_asset(ticker):
        if ticker == "CVNA":
            return (20.0, "Exit", "Technology", 100.0)
        return (75.0, "High", "Technology", 200.0)

    def fake_get_technicals(ticker):
        if ticker == "CVNA":
            return {"macd": "bearish", "ma50": "bearish", "rsi_failure_swing": "neutral"}
        return {"macd": "bullish", "ma50": "bullish", "rsi_failure_swing": "neutral"}

    monkeypatch.setattr(portfolio_app, "score_asset", fake_score_asset)
    monkeypatch.setattr(portfolio_app, "get_technicals", fake_get_technicals)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": "CVNA", "shares": "10", "invested": "1000", "type": "main"},
        {"ticker": "NVDA", "shares": "5", "invested": "500", "type": "main"},
    ]
    result = portfolio_app.run_scoring(holdings)
    by_ticker = {p["ticker"]: p for p in result["positions"]}

    assert by_ticker["CVNA"]["days_until_eligible"] == 3
    assert by_ticker["NVDA"]["days_until_eligible"] is None
    assert by_ticker["NVDA"]["watchlisted_since"] is None
