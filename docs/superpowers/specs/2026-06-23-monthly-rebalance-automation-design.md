# Monthly Rebalance Automation (Phase 4)

## Goal

Automatically generate the existing PDF snapshot report once a month, with no user interaction
required, so the portfolio gets a periodic check-in even when nobody opens the app.

## Background

This is the last phase of the original 4-phase rebuild plan. The original plan called for a
standalone `rebalancer.py` script, a monthly cron job ("1st Saturday each month"), fresh signal
generation (sell/trim/re-entry/new-opportunity), and an emailed report.

Scope was substantially simplified during brainstorming:

- **No email.** Since this runs locally on the user's own machine, the report is just saved to
  disk — the existing `reports/` directory already used by the manually-triggered PDF snapshot
  feature (Phase "PDF snapshot report").
- **No new signal-generation logic.** Every signal the original plan asked for (sell, trim,
  re-entry, new opportunities) is already computed by the existing scoring engine
  (`momentum_signal`, `action`, `over_position_cap`, `tax_harvest_candidate` from Phases 1-3b).
  This phase doesn't add scoring logic — it just runs the existing pipeline on a schedule.
- **No new report format.** The existing `generate_pdf_report()` (from the PDF snapshot phase)
  is reused as-is, not replaced with a filtered "action items only" report.
- **Fixed day-of-month, not "1st Saturday."** `cron`/`launchd` can't express "nth weekday"
  directly, and the original "1st Saturday" intent isn't worth the added complexity of a
  self-checking script. The 1st of every month is functionally equivalent for this purpose.

## Architecture

A new standalone script, `monthly_rebalance.py`, lives alongside `portfolio_app.py` but is never
imported by it — the dependency is one-directional (the script imports `portfolio_app`, not the
reverse). It contains no new business logic:

```python
import portfolio_app

data = portfolio_app.load_data()
holdings = [h for h in data.get("main", []) + data.get("trial", [])
            if h.get("ticker") and float(h.get("shares") or 0) > 0]
result = portfolio_app.run_scoring(holdings)
if "error" in result:
    print(f"Skipped: {result['error']}")
else:
    path = portfolio_app.generate_pdf_report(result)
    print(f"Saved monthly report to {path}")
```

The holdings filter (`ticker` present, `shares > 0`, main + trial combined) mirrors exactly the
filter the frontend's `analyze()` function already uses before calling `/api/score` — no new
filtering rule is invented.

`run_scoring()`, `generate_pdf_report()`, and `load_data()` have no Flask request-context
dependency (verified: no `request.` usage in any of their bodies), so they can be called
directly from a plain script with no Flask app instance needed.

**Scheduling**: a single cron entry, run on the 1st of each month:

```
0 9 1 * * cd /Users/thomasmacbook/Desktop/Pmanager && /usr/bin/python3 monthly_rebalance.py >> monthly_rebalance.log 2>&1
```

Adding this to the user's crontab is a standing background automation, not a one-off reversible
action — the implementation plan must walk through this exact command with the user and get
explicit confirmation before installing it, rather than adding it silently.

## Error Handling

- **`run_scoring()` returns an error dict** (e.g. no valid holdings): printed and the script
  exits cleanly, without calling `generate_pdf_report()` — no partial/empty report is written.
- **Network/yfinance failures**: already handled internally by the existing `get_price_history`/
  `score_asset` fallback behavior; no new handling needed in this script.
- **`portfolio_data.json` doesn't exist yet**: `load_data()` already returns blank slots in that
  case; the holdings filter then produces an empty list, which `run_scoring([])` turns into the
  same "no valid holdings" error path above.
- **Logging**: since this runs unattended, the cron entry redirects stdout/stderr to
  `monthly_rebalance.log` so failures are visible after the fact rather than silently lost.

## Testing

- A test mocking `portfolio_app.load_data`/`run_scoring`/`generate_pdf_report` to confirm the
  script's holdings-filtering logic (ticker present, shares > 0, main + trial combined) produces
  the same result as the existing frontend filter for an equivalent input.
- A test confirming the script handles `run_scoring` returning an error dict gracefully — no
  exception raised, `generate_pdf_report` never called.
- Manual verification: run `python3 monthly_rebalance.py` once by hand against real holdings,
  confirm a dated PDF appears in `reports/` matching today's date.

## Explicitly Out of Scope

- Email delivery (descoped during brainstorming — local save only).
- A new, filtered "action items only" report format (descoped — reuses the existing full PDF
  snapshot as-is).
- True "1st Saturday of the month" scheduling logic (descoped — fixed day-of-month instead).
- Any new scoring/signal-generation logic (everything needed already exists from Phases 1-3b).
