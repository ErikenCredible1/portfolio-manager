import portfolio_app


def test_api_save_snapshot_returns_path_on_success(monkeypatch):
    monkeypatch.setattr(portfolio_app, "run_scoring", lambda holdings: {
        "total_value": 100.0, "total_invested": 90.0, "total_pnl": 10.0,
        "positions": [{
            "ticker": "NVDA", "name": "NVIDIA", "score": 75.0, "tier": "High",
            "pnl": 10.0, "pnl_pct": 0.11, "action": "BUY", "momentum_signal": "BUY",
            "pos_type": "main",
        }],
    })
    monkeypatch.setattr(
        portfolio_app, "generate_pdf_report",
        lambda result: "reports/portfolio_report_2026-06-21.pdf",
    )

    client = portfolio_app.app.test_client()
    resp = client.post("/api/save-snapshot", json={
        "holdings": [{"ticker": "NVDA", "shares": "1", "invested": "10"}],
    })
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["path"] == "reports/portfolio_report_2026-06-21.pdf"


def test_api_save_snapshot_returns_400_when_scoring_errors(monkeypatch):
    monkeypatch.setattr(
        portfolio_app, "run_scoring",
        lambda holdings: {"error": "No valid holdings — make sure share counts are filled in."},
    )

    client = portfolio_app.app.test_client()
    resp = client.post("/api/save-snapshot", json={"holdings": []})
    data = resp.get_json()
    assert resp.status_code == 400
    assert data["error"] == "No valid holdings — make sure share counts are filled in."


def test_api_save_snapshot_returns_500_on_unexpected_exception(monkeypatch):
    def boom(holdings):
        raise RuntimeError("yfinance unreachable")

    monkeypatch.setattr(portfolio_app, "run_scoring", boom)

    client = portfolio_app.app.test_client()
    resp = client.post("/api/save-snapshot", json={"holdings": [{"ticker": "NVDA", "shares": "1"}]})
    data = resp.get_json()
    assert resp.status_code == 500
    assert "yfinance unreachable" in data["error"]
