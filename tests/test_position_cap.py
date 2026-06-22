import portfolio_app


def _technicals_neutral(ticker):
    return {"macd": "neutral", "ma50": "neutral", "rsi_failure_swing": "neutral"}


def test_run_scoring_flags_lowest_scoring_positions_beyond_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    scores = {f"T{i}": float(i) for i in range(1, 37)}  # T1..T36, scores 1..36

    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (scores[ticker], "Medium", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": f"T{i}", "shares": "1", "invested": "100", "type": "main"}
        for i in range(1, 37)
    ]
    result = portfolio_app.run_scoring(holdings)
    by_ticker = {p["ticker"]: p for p in result["positions"]}

    assert by_ticker["T1"]["over_position_cap"] is True    # lowest score, 1 over the cap of 35
    assert by_ticker["T2"]["over_position_cap"] is False    # rank 35 from the top, just inside
    assert by_ticker["T36"]["over_position_cap"] is False   # highest score


def test_run_scoring_does_not_flag_anyone_at_or_under_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    scores = {f"T{i}": float(i) for i in range(1, 36)}  # T1..T35, exactly at the cap

    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (scores[ticker], "Medium", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": f"T{i}", "shares": "1", "invested": "100", "type": "main"}
        for i in range(1, 36)
    ]
    result = portfolio_app.run_scoring(holdings)

    assert all(p["over_position_cap"] is False for p in result["positions"])


def test_run_scoring_never_flags_trial_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    # 36 main positions (scores 1..36) plus one trial position with the lowest score of all --
    # the trial position must never be flagged, even though it would rank last overall.
    scores = {f"T{i}": float(i) for i in range(1, 37)}
    scores["TRIAL1"] = 0.0

    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (scores[ticker], "Medium", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": f"T{i}", "shares": "1", "invested": "100", "type": "main"}
        for i in range(1, 37)
    ] + [{"ticker": "TRIAL1", "shares": "1", "invested": "100", "type": "trial"}]

    result = portfolio_app.run_scoring(holdings)
    by_ticker = {p["ticker"]: p for p in result["positions"]}

    assert by_ticker["TRIAL1"]["over_position_cap"] is False
    assert by_ticker["T1"]["over_position_cap"] is True  # lowest-scoring main position instead
