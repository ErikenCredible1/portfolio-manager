# Monthly Rebalance Automation (Phase 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Task 2 in this plan must NOT be dispatched to an implementer subagent.** It requires live
> user confirmation before modifying the system crontab — a standing background automation, not
> a one-off reversible code change. The controller (you, reading this) must perform Task 2's
> steps directly and get explicit user sign-off before running the `crontab` command.

**Goal:** Automatically generate the existing PDF snapshot report once a month, with no user
interaction required.

**Architecture:** A new standalone script, `monthly_rebalance.py`, imports `portfolio_app` and
calls three already-existing, already-tested functions (`load_data`, `run_scoring`,
`generate_pdf_report`) — no new scoring or report-generation logic. A cron entry triggers it on
the 1st of each month.

**Tech Stack:** Python (existing — no new dependencies), cron (system scheduler, no new package).

## Global Constraints

- `monthly_rebalance.py` lives at the project root, alongside `portfolio_app.py`. It imports
  `portfolio_app`; `portfolio_app.py` never imports it back (one-directional dependency).
- Holdings filter: `ticker` present AND `shares > 0`, main + trial combined — must match
  exactly what the frontend's `analyze()` function already filters on before calling
  `/api/score`.
- If `run_scoring()` returns an `"error"` key, the script must print it and return without
  calling `generate_pdf_report()` — no partial/empty report written.
- No email delivery, no new report format, no "1st Saturday" date-matching logic (fixed
  day-of-month cron schedule instead) — all explicitly out of scope per the spec.
- Tests run from the project root with: `python3 -m pytest tests/ -v`

---

## File Structure

- **Create:** `monthly_rebalance.py` — the standalone script.
- **Create:** `tests/test_monthly_rebalance.py`

---

### Task 1: `monthly_rebalance.py` script

**Files:**
- Create: `monthly_rebalance.py`
- Create: `tests/test_monthly_rebalance.py`

**Interfaces:**
- Consumes: `portfolio_app.load_data() -> dict`, `portfolio_app.run_scoring(holdings) -> dict`,
  `portfolio_app.generate_pdf_report(result) -> str` (all existing, unchanged).
- Produces: `get_scoreable_holdings(data: dict) -> list[dict]`, `main() -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_monthly_rebalance.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_monthly_rebalance.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'monthly_rebalance'`

- [ ] **Step 3: Implement the script**

Create `monthly_rebalance.py`:

```python
"""
Monthly Rebalance Automation
=============================
Runs the existing scoring engine and generates a dated PDF snapshot, with no
user interaction. Intended to be triggered by cron on the 1st of each month.

RUN MANUALLY:
    python3 monthly_rebalance.py

SCHEDULE (cron, runs at 9am on the 1st of each month):
    0 9 1 * * cd /Users/thomasmacbook/Desktop/Pmanager && /usr/bin/python3 monthly_rebalance.py >> monthly_rebalance.log 2>&1
"""

import portfolio_app


def get_scoreable_holdings(data):
    return [
        h for h in data.get("main", []) + data.get("trial", [])
        if h.get("ticker") and float(h.get("shares") or 0) > 0
    ]


def main():
    data = portfolio_app.load_data()
    holdings = get_scoreable_holdings(data)
    result = portfolio_app.run_scoring(holdings)
    if "error" in result:
        print(f"Skipped: {result['error']}")
        return
    path = portfolio_app.generate_pdf_report(result)
    print(f"Saved monthly report to {path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_monthly_rebalance.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests, including everything from every prior phase)

- [ ] **Step 6: Commit**

```bash
git add tests/test_monthly_rebalance.py monthly_rebalance.py
git commit -m "feat: add monthly_rebalance.py standalone script"
```

---

### Task 2: Manual verification and cron setup (controller-performed, NOT a subagent dispatch)

**This task must be performed directly by the controller, with the user, not delegated to an
implementer subagent.** Installing a cron entry is a standing background automation, not a
one-off code change — the design spec explicitly requires walking through the exact command
with the user and getting confirmation before installing it.

- [ ] **Step 1: Run the script once manually against real holdings**

```bash
cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 monthly_rebalance.py
```

Confirm a new file `reports/portfolio_report_<today's date>.pdf` exists and is non-empty, and
that the script's printed output says `Saved monthly report to ...` (not `Skipped: ...`).

- [ ] **Step 2: Present the cron command to the user and get explicit confirmation**

Show the user this exact command and ask whether they want it installed:

```
0 9 1 * * cd /Users/thomasmacbook/Desktop/Pmanager && /usr/bin/python3 monthly_rebalance.py >> /Users/thomasmacbook/Desktop/Pmanager/monthly_rebalance.log 2>&1
```

Explain: this runs at 9am on the 1st of every month, regardless of weekday. Output (including
any errors) is appended to `monthly_rebalance.log` in the project directory.

- [ ] **Step 3: If confirmed, install it**

```bash
(crontab -l 2>/dev/null; echo "0 9 1 * * cd /Users/thomasmacbook/Desktop/Pmanager && /usr/bin/python3 monthly_rebalance.py >> /Users/thomasmacbook/Desktop/Pmanager/monthly_rebalance.log 2>&1") | crontab -
```

This appends the new line to the user's existing crontab without overwriting any other entries
(`crontab -l` lists the current table; piping it plus the new line into `crontab -` replaces the
table with the old contents plus the new line).

- [ ] **Step 4: Verify the entry was installed**

```bash
crontab -l
```

Confirm the new line appears in the output.

- [ ] **Step 5: Tell the user how to remove it later if they want to**

```
crontab -e
```

(opens the crontab in an editor where they can delete the line manually), or for a full reset:
`crontab -l | grep -v monthly_rebalance.py | crontab -`.

---

## Self-Review

**Spec coverage:** Standalone script reusing existing `load_data`/`run_scoring`/
`generate_pdf_report`, no new scoring logic (Task 1) ✓. Holdings filter matching the frontend's
existing filter exactly (Task 1) ✓. Error-dict handling, no partial report on failure (Task 1)
✓. Fixed day-of-month cron schedule, explicit user confirmation before installing it (Task 2) ✓.
No email, no new report format — neither task implements either, matching the spec's
out-of-scope list.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code or exact
commands.

**Type consistency:** `get_scoreable_holdings(data: dict) -> list[dict]` and `main() -> None`
match exactly between Task 1's implementation and its own tests — no other task references
these names, so there's no cross-task drift to check.
