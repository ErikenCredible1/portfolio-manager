import monthly_rebalance


def test_get_scoreable_holdings_filters_empty_ticker_and_zero_shares():
    data = {
        "main": [
            {"ticker": "NVDA", "shares": "10", "invested": "1000", "type": "main"},
            {"ticker": "", "shares": "5", "invested": "100", "type": "main"},
            {"ticker": "AMD", "shares": "0", "invested": "200", "type": "main"},
        ],
        "trial": [
            {"ticker": "SOFI", "shares": "20", "invested": "300", "type": "trial"},
        ],
    }
    holdings = monthly_rebalance.get_scoreable_holdings(data)
    tickers = {h["ticker"] for h in holdings}
    assert tickers == {"NVDA", "SOFI"}


def test_get_scoreable_holdings_handles_missing_shares_key():
    data = {"main": [{"ticker": "NVDA", "invested": "1000", "type": "main"}], "trial": []}
    holdings = monthly_rebalance.get_scoreable_holdings(data)
    assert holdings == []


def test_main_skips_report_generation_when_run_scoring_returns_error(monkeypatch, capsys):
    monkeypatch.setattr(monthly_rebalance.portfolio_app, "load_data",
                         lambda: {"main": [], "trial": []})
    monkeypatch.setattr(monthly_rebalance.portfolio_app, "run_scoring",
                         lambda holdings: {"error": "No valid holdings — make sure share counts are filled in."})

    called = {"generate_pdf_report": False}

    def fake_generate_pdf_report(result):
        called["generate_pdf_report"] = True
        return "reports/should-not-be-called.pdf"

    monkeypatch.setattr(monthly_rebalance.portfolio_app, "generate_pdf_report", fake_generate_pdf_report)

    monthly_rebalance.main()

    assert called["generate_pdf_report"] is False
    captured = capsys.readouterr()
    assert "Skipped" in captured.out


def test_main_generates_report_when_run_scoring_succeeds(monkeypatch, capsys):
    monkeypatch.setattr(
        monthly_rebalance.portfolio_app, "load_data",
        lambda: {"main": [{"ticker": "NVDA", "shares": "10", "invested": "1000", "type": "main"}], "trial": []},
    )
    monkeypatch.setattr(
        monthly_rebalance.portfolio_app, "run_scoring",
        lambda holdings: {"positions": [], "total_value": 0, "total_invested": 0, "total_pnl": 0},
    )
    monkeypatch.setattr(
        monthly_rebalance.portfolio_app, "generate_pdf_report",
        lambda result: "reports/portfolio_report_2026-06-23.pdf",
    )

    monthly_rebalance.main()

    captured = capsys.readouterr()
    assert "Saved monthly report" in captured.out
