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
