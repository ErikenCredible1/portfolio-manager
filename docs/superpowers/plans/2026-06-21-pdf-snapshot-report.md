# Dated PDF Snapshot Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every time the user clicks Save, also generate a dated PDF report of their live-scored
portfolio, without slowing down or risking the existing fast/reliable holdings save.

**Architecture:** A new pure function `generate_pdf_report(result)` renders a `run_scoring()`-shaped
dict to a dated PDF via `fpdf2`. A new `/api/save-snapshot` Flask route wires `run_scoring()` +
`generate_pdf_report()` together, called by the frontend as a second, independent step right
after `/api/save` succeeds — never blocking or affecting the holdings save itself.

**Tech Stack:** Flask, `fpdf2` (new dependency — pure Python, no system-level dependencies).

## Global Constraints

- PDF library: `fpdf2`, installed via `pip3 install fpdf2`.
- Report path: `reports/portfolio_report_<YYYY-MM-DD>.pdf` (today's date, server-local time).
  Saving again the same day overwrites that day's file — one report per day, not one per save.
- `reports/` is gitignored (derived from real financial data, same as `portfolio_data.json`).
- `/api/save` (existing route) is never modified — holdings persistence stays exactly as fast
  and reliable as it is today, independent of scoring/PDF success or failure.
- PDF content: one table per `pos_type` ("main", "trial"), columns Ticker/Name/Score/Tier/P&L $/P&L %/Action/Momentum,
  in the order `run_scoring()` already returns (sorted by score descending), plus a summary line
  (total value, total invested, total P&L, generation timestamp).

---

## File Structure

- **Modify:** `portfolio_app.py` — add `REPORTS_DIR` constant, `generate_pdf_report()` +
  `_position_table_rows()` + `_render_table()` helpers, the `/api/save-snapshot` route, and the
  frontend `savePortfolio()` JS function.
- **Modify:** `.gitignore` — add `reports/`.
- **Create:** `tests/test_pdf_report.py`
- **Create:** `tests/test_save_snapshot_route.py`

---

### Task 1: PDF rendering function

**Files:**
- Create: `tests/test_pdf_report.py`
- Modify: `portfolio_app.py` (add `REPORTS_DIR` constant near `WATCHLIST_FILE`; add
  `generate_pdf_report`, `_position_table_rows`, `_render_table` in a new section after the
  "TECHNICAL INDICATORS & MOMENTUM SIGNAL" section, before `target_allocation`)

**Interfaces:**
- Produces: `generate_pdf_report(result: dict) -> str`, where `result` has the same shape as
  `run_scoring()`'s return value (`positions`, `total_value`, `total_invested`, `total_pnl`).
  Returns the path to the written PDF file.

- [ ] **Step 1: Install fpdf2**

```bash
pip3 install fpdf2
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_pdf_report.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_pdf_report.py -v`
Expected: FAIL with `ImportError: cannot import name 'generate_pdf_report'`

- [ ] **Step 4: Implement the PDF rendering function**

In `portfolio_app.py`, near the `WATCHLIST_FILE` constant, add:

```python
REPORTS_DIR = "reports"
```

Add `from fpdf import FPDF` to the imports near the top of the file, alongside the other
third-party imports (`import numpy as np`, etc.).

In the "TECHNICAL INDICATORS & MOMENTUM SIGNAL" section, after `evaluate_momentum_signal` and
before `target_allocation`, add:

```python
def _position_table_rows(positions):
    return [
        [
            p["ticker"],
            (p.get("name") or "")[:25],
            f'{p["score"]:.1f}',
            p["tier"],
            f'${p["pnl"]:.2f}',
            f'{p["pnl_pct"] * 100:.1f}%',
            p["action"],
            p["momentum_signal"],
        ]
        for p in positions
    ]


def _render_table(pdf, title, headers, col_widths, rows):
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, title)
    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 9)
    for header, width in zip(headers, col_widths):
        pdf.cell(width, 7, header, 1)
    pdf.ln(7)

    pdf.set_font("Helvetica", "", 9)
    for row in rows:
        for value, width in zip(row, col_widths):
            pdf.cell(width, 6, str(value), 1)
        pdf.ln(6)


def generate_pdf_report(result):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(REPORTS_DIR, f"portfolio_report_{date_str}.pdf")

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Portfolio Report")
    pdf.ln(10)

    pdf.set_font("Helvetica", "", 10)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    pdf.cell(0, 6, f"Generated: {generated_at}")
    pdf.ln(6)
    pdf.cell(0, 6, (
        f"Total Value: ${result['total_value']:.2f}   "
        f"Total Invested: ${result['total_invested']:.2f}   "
        f"Total P&L: ${result['total_pnl']:.2f}"
    ))
    pdf.ln(10)

    headers    = ["Ticker", "Name", "Score", "Tier", "P&L $", "P&L %", "Action", "Momentum"]
    col_widths = [20, 55, 18, 18, 25, 20, 22, 25]

    main_positions  = [p for p in result["positions"] if p["pos_type"] == "main"]
    trial_positions = [p for p in result["positions"] if p["pos_type"] == "trial"]

    _render_table(pdf, "Main Positions", headers, col_widths, _position_table_rows(main_positions))
    if trial_positions:
        pdf.ln(6)
        _render_table(pdf, "Trial Positions", headers, col_widths, _position_table_rows(trial_positions))

    pdf.output(path)
    return path
```

Note: `cell()`'s text argument is passed positionally (not as a `txt=`/`text=` keyword) and line
breaks use explicit `pdf.ln(height)` calls rather than the `ln=` parameter on `cell()` — this
avoids depending on which exact `fpdf2` version is installed, since the keyword name for the text
argument changed between versions but positional calls work on both.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_pdf_report.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/test_pdf_report.py portfolio_app.py
git commit -m "feat: add generate_pdf_report for dated portfolio snapshots"
```

---

### Task 2: `/api/save-snapshot` route

**Files:**
- Create: `tests/test_save_snapshot_route.py`
- Modify: `portfolio_app.py` (add the new route after `/api/score`)

**Interfaces:**
- Consumes: `run_scoring(holdings)` (existing, unchanged), `generate_pdf_report(result)` (Task 1).
- Produces: `POST /api/save-snapshot` — request body `{"holdings": [...]}` (same shape as
  `/api/score`). Response `{"ok": true, "path": "<str>"}` on success (200), or
  `{"error": "<str>"}` on failure (400 if `run_scoring` itself returned an error dict, 500 on an
  unexpected exception).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_save_snapshot_route.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_save_snapshot_route.py -v`
Expected: FAIL with `404 NOT FOUND` (route doesn't exist yet) — the test asserts on `resp.status_code`/`resp.get_json()`, which will not match the expected values.

- [ ] **Step 3: Implement the route**

In `portfolio_app.py`, directly after the existing `/api/score` route (`api_score`) and before
`/api/price/<ticker>`, add:

```python
@app.route("/api/save-snapshot", methods=["POST"])
def api_save_snapshot():
    holdings = request.json.get("holdings", [])
    try:
        result = run_scoring(holdings)
        if "error" in result:
            return jsonify(result), 400
        path = generate_pdf_report(result)
        return jsonify({"ok": True, "path": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_save_snapshot_route.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests from this plan plus all prior Phase 1 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/test_save_snapshot_route.py portfolio_app.py
git commit -m "feat: add /api/save-snapshot route"
```

---

### Task 3: Wire into Save, update .gitignore, manual verification

**Files:**
- Modify: `portfolio_app.py:1068-1074` (the `savePortfolio()` JS function)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `/api/save-snapshot` (Task 2).
- No new Python interfaces — this is frontend JS embedded in the `HTML_PAGE` string, plus a
  `.gitignore` entry.

- [ ] **Step 1: Add `reports/` to `.gitignore`**

In `.gitignore`, add a new line under the existing "Personal portfolio data" section:

```
# Generated PDF snapshots (derived from real holdings data)
reports/
```

- [ ] **Step 2: Update `savePortfolio()` to also trigger a snapshot**

In `portfolio_app.py`, replace the existing `savePortfolio()` function:

```js
async function savePortfolio() {
  await fetch('/api/save', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({main: mainData, trial: trialData})
  });
  toast('Saved ✓');
}
```

with:

```js
async function savePortfolio() {
  await fetch('/api/save', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({main: mainData, trial: trialData})
  });
  toast('Saved ✓');

  const holdings = [...mainData, ...trialData].filter(d => d.ticker && parseFloat(d.shares) > 0);
  if (!holdings.length) return;

  try {
    const res  = await fetch('/api/save-snapshot', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({holdings})
    });
    const data = await res.json();
    if (data.error) toast('Saved, but snapshot failed: ' + data.error, true);
  } catch (e) {
    toast('Saved, but snapshot failed: ' + e.message, true);
  }
}
```

This never blocks or affects the holdings save above — the `/api/save` call and its toast happen
first and unconditionally; the snapshot is a best-effort follow-up.

- [ ] **Step 3: Manually verify in the browser**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 portfolio_app.py`

In the browser that opens:
1. Make sure at least one position has a ticker and a share count filled in.
2. Click Save.
3. Confirm the "Saved ✓" toast appears, and no "snapshot failed" toast appears (if it does, note
   the error — likely a network/yfinance issue, not a bug in this feature).

Then check the filesystem:

```bash
ls -la "/Users/thomasmacbook/Desktop/Pmanager/reports/"
```

Expected: a file named `portfolio_report_<today's date>.pdf` exists and is non-empty. Open it to
confirm it contains a readable table of your positions with scores, tiers, P&L, action, and
momentum signal columns.

Click Save again — confirm the same file is overwritten (check its modification timestamp
changes) rather than a second file being created.

Stop the server with Ctrl+C when done.

- [ ] **Step 4: Commit**

```bash
git add portfolio_app.py .gitignore
git commit -m "feat: trigger PDF snapshot generation after Save"
```

---

## Self-Review

**Spec coverage:** Decoupled `/api/save-snapshot` route, never modifying `/api/save` (Task 2) ✓.
`fpdf2`, pure-Python, no system dependencies (Task 1) ✓. Dated filename, overwrite-same-day
behavior (Task 1) ✓. Live scores/prices via `run_scoring` (Task 2) ✓. Main/trial split into two
tables (Task 1) ✓. Error handling for scoring failure and unexpected exceptions (Task 2) ✓.
`reports/` gitignored (Task 3) ✓. Frontend trigger on Save, non-blocking (Task 3) ✓. Manual
verification of the full Save → snapshot → file-on-disk flow (Task 3) ✓.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `generate_pdf_report(result)` (Task 1) takes the exact same `result` shape
`api_save_snapshot` (Task 2) passes it — both reference `result["positions"]`, `result["total_value"]`,
`result["total_invested"]`, `result["total_pnl"]`, and each position's `ticker`/`name`/`score`/`tier`/
`pnl`/`pnl_pct`/`action`/`momentum_signal`/`pos_type` keys, matching exactly what `run_scoring()`
already produces (confirmed against `portfolio_app.py`'s existing `run_scoring` return shape).
