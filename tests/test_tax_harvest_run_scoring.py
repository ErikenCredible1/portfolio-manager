import portfolio_app


def _technicals_neutral(ticker):
    return {"macd": "neutral", "ma50": "neutral", "rsi_failure_swing": "neutral"}


def test_run_scoring_flags_tax_harvest_candidates_in_december(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: True)

    prices = {"LOSER": (20.0, "Exit", "Technology", 50.0), "WINNER": (75.0, "High", "Technology", 200.0)}
    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: prices[ticker])
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": "LOSER", "shares": "10", "invested": "1000", "type": "main"},   # value=500, pnl=-500
        {"ticker": "WINNER", "shares": "5", "invested": "500", "type": "main"},    # value=1000, pnl=+500
    ]
    result = portfolio_app.run_scoring(holdings)
    by_ticker = {p["ticker"]: p for p in result["positions"]}

    assert by_ticker["LOSER"]["tax_harvest_candidate"] is True
    assert by_ticker["WINNER"]["tax_harvest_candidate"] is False
    assert result["tax_harvest_target_remaining"] == 3000
    assert result["tax_harvest_realized_this_year"] == 0


def test_run_scoring_never_flags_tax_harvest_candidates_outside_december(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: False)

    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: (20.0, "Exit", "Technology", 50.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "LOSER", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)

    assert result["positions"][0]["tax_harvest_candidate"] is False
    assert result["tax_harvest_target_remaining"] is None
    assert result["tax_harvest_realized_this_year"] is None


def test_run_scoring_target_remaining_reduced_by_prior_realized_losses(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: True)
    portfolio_app.log_realized_sale("OLDSALE", -1200.0, "main")

    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: (20.0, "Exit", "Technology", 50.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "LOSER", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)

    assert result["tax_harvest_realized_this_year"] == 1200
    assert result["tax_harvest_target_remaining"] == 1800  # 3000 - 1200


def test_run_scoring_includes_wash_sale_clear_date_for_recently_logged_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: False)
    portfolio_app.log_realized_sale("NVDA", -300.0, "main")

    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: (75.0, "High", "Technology", 200.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bullish", "ma50": "bullish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "NVDA", "shares": "5", "invested": "500", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)
    pos = result["positions"][0]

    assert pos["wash_sale_clear_date"] is not None
    assert pos["momentum_signal"] in ("BUY", "RE_ENTRY")  # unaffected by wash-sale status
