import os
from datetime import datetime

import portfolio_app
from portfolio_app import generate_pdf_report


def _fake_result():
    return {
        "total_value": 1000.0,
        "total_invested": 800.0,
        "total_pnl": 200.0,
        "positions": [
            {"ticker": "NVDA", "name": "NVIDIA Corporation", "score": 75.0, "tier": "High",
             "pnl": 150.0, "pnl_pct": 0.15, "action": "BUY", "momentum_signal": "BUY",
             "pos_type": "main"},
            {"ticker": "CVNA", "name": "Carvana Co", "score": 20.0, "tier": "Exit",
             "pnl": -50.0, "pnl_pct": -0.10, "action": "TRIM", "momentum_signal": "TRIM_TO_100",
             "pos_type": "trial"},
        ],
    }


def test_generate_pdf_report_writes_valid_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REPORTS_DIR", str(tmp_path / "reports"))
    path = generate_pdf_report(_fake_result())
    assert os.path.exists(path)
    with open(path, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"
    assert os.path.getsize(path) > 0


def test_generate_pdf_report_filename_includes_todays_date(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REPORTS_DIR", str(tmp_path / "reports"))
    path = generate_pdf_report(_fake_result())
    today = datetime.now().strftime("%Y-%m-%d")
    assert today in os.path.basename(path)


def test_generate_pdf_report_overwrites_same_day_file(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REPORTS_DIR", str(tmp_path / "reports"))
    path1 = generate_pdf_report(_fake_result())
    path2 = generate_pdf_report(_fake_result())
    assert path1 == path2
    assert os.path.exists(path2)


def test_generate_pdf_report_handles_no_trial_positions(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REPORTS_DIR", str(tmp_path / "reports"))
    result = _fake_result()
    result["positions"] = [p for p in result["positions"] if p["pos_type"] == "main"]
    path = generate_pdf_report(result)
    assert os.path.exists(path)
    assert os.path.getsize(path) > 0


def test_generate_pdf_report_actually_contains_position_data(tmp_path, monkeypatch):
    # Compression is disabled in generate_pdf_report specifically so table content
    # is greppable here -- this catches silently-dropped rows or omitted tables that
    # the file-level checks above (existence, size, magic bytes) would miss.
    monkeypatch.setattr(portfolio_app, "REPORTS_DIR", str(tmp_path / "reports"))
    path = generate_pdf_report(_fake_result())
    with open(path, "rb") as f:
        data = f.read()
    assert b"NVDA" in data
    assert b"CVNA" in data
    assert b"Main Positions" in data
    assert b"Trial Positions" in data


def test_generate_pdf_report_omits_trial_table_when_no_trial_positions(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REPORTS_DIR", str(tmp_path / "reports"))
    result = _fake_result()
    result["positions"] = [p for p in result["positions"] if p["pos_type"] == "main"]
    path = generate_pdf_report(result)
    with open(path, "rb") as f:
        data = f.read()
    assert b"NVDA" in data
    assert b"CVNA" not in data
    assert b"Trial Positions" not in data
