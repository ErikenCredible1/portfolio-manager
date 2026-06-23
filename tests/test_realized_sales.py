from datetime import datetime, timedelta

import portfolio_app
from portfolio_app import (
    load_realized_sales,
    log_realized_sale,
    realized_losses_this_year,
    wash_sale_clear_date_for,
)


def test_log_realized_sale_persists_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    log_realized_sale("CVNA", -450.0, "main")
    state = load_realized_sales()
    assert len(state["sales"]) == 1
    assert state["sales"][0]["ticker"] == "CVNA"
    assert state["sales"][0]["amount"] == -450.0
    assert state["sales"][0]["pos_type"] == "main"


def test_realized_losses_this_year_sums_losses_only(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    log_realized_sale("CVNA", -450.0, "main")
    log_realized_sale("NVDA", 800.0, "main")   # a gain -- must not count
    log_realized_sale("SOFI", -200.0, "trial")
    assert realized_losses_this_year() == -650.0


def test_realized_losses_this_year_excludes_prior_year(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    state = {"sales": [
        {"ticker": "OLD", "amount": -999.0, "date": "2020-01-01T00:00:00", "pos_type": "main"},
    ]}
    portfolio_app.save_realized_sales(state)
    log_realized_sale("CVNA", -100.0, "main")
    assert realized_losses_this_year() == -100.0


def test_realized_losses_this_year_is_zero_when_no_sales(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    assert realized_losses_this_year() == 0


def test_wash_sale_clear_date_for_within_window(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    log_realized_sale("CVNA", -450.0, "main")
    clear_date = wash_sale_clear_date_for("CVNA")
    assert clear_date is not None
    expected = datetime.now() + timedelta(days=portfolio_app.WASH_SALE_DAYS)
    assert abs((clear_date - expected).total_seconds()) < 5


def test_wash_sale_clear_date_for_outside_window_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    old_date = (datetime.now() - timedelta(days=40)).isoformat()
    state = {"sales": [{"ticker": "CVNA", "amount": -450.0, "date": old_date, "pos_type": "main"}]}
    portfolio_app.save_realized_sales(state)
    assert wash_sale_clear_date_for("CVNA") is None


def test_wash_sale_clear_date_for_no_history_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    assert wash_sale_clear_date_for("NVDA") is None


def test_wash_sale_clear_date_for_uses_most_recent_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    old_date = (datetime.now() - timedelta(days=40)).isoformat()
    state = {"sales": [{"ticker": "CVNA", "amount": -100.0, "date": old_date, "pos_type": "main"}]}
    portfolio_app.save_realized_sales(state)
    log_realized_sale("CVNA", -50.0, "main")  # more recent than the 40-day-old entry
    assert wash_sale_clear_date_for("CVNA") is not None  # governed by the recent entry
