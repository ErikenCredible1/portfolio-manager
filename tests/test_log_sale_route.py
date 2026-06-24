import portfolio_app


def test_api_log_sale_persists_entry_with_uppercased_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    client = portfolio_app.app.test_client()
    resp = client.post("/api/log-sale", json={"ticker": "cvna", "amount": -450.0, "pos_type": "main"})
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    state = portfolio_app.load_realized_sales()
    assert state["sales"][0]["ticker"] == "CVNA"
    assert state["sales"][0]["amount"] == -450.0


def test_api_log_sale_defaults_pos_type_to_main(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    client = portfolio_app.app.test_client()
    resp = client.post("/api/log-sale", json={"ticker": "NVDA", "amount": -100.0})

    assert resp.status_code == 200
    state = portfolio_app.load_realized_sales()
    assert state["sales"][0]["pos_type"] == "main"
