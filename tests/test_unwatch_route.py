import portfolio_app


def test_api_unwatch_clears_watchlist_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    portfolio_app.flag_watchlisted("NVDA")
    assert portfolio_app.is_watchlisted("NVDA") is True

    client = portfolio_app.app.test_client()
    resp = client.post("/api/unwatch", json={"ticker": "NVDA"})
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert portfolio_app.is_watchlisted("NVDA") is False


def test_api_unwatch_on_never_flagged_ticker_does_not_error(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    client = portfolio_app.app.test_client()
    resp = client.post("/api/unwatch", json={"ticker": "NVDA"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
