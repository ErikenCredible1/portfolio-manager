# Dated PDF Snapshot Report

## Goal

Every time the user clicks Save, also generate a dated PDF report of their current portfolio
(live scores, tiers, P&L, action, momentum_signal) — building a historical record over time
without any extra steps. This was explicitly deferred during the Phase 1 (scoring engine)
brainstorm as a separate, unrelated data-persistence feature.

## Architecture

A new `/api/save-snapshot` POST route, called by the frontend immediately after a successful
`/api/save` call. It does not modify `/api/save` or `save_data()` in any way — holdings
persistence stays exactly as fast and reliable as it is today, independent of network or PDF
status.

`/api/save-snapshot`:
1. Receives the same `{"holdings": [...]}` payload the frontend already sends to `/api/score`.
2. Calls the existing `run_scoring(holdings)` (unchanged) to get live scores/prices.
3. Renders a PDF from the result using `fpdf2` — chosen because it's pure Python with no
   system-level dependencies (this matters specifically on this machine, which has no
   Homebrew/admin rights to install something like `weasyprint`, which needs system graphics
   libraries).
4. Writes the PDF to `reports/portfolio_report_<YYYY-MM-DD>.pdf` (today's date, server-local
   time), overwriting if a report for today already exists — one report per day, not one per
   save.
5. Returns `{"ok": true, "path": "<relative path>"}` on success.

The `reports/` directory is created if missing and added to `.gitignore` (it's derived from the
user's real financial data, same rationale as `portfolio_data.json`).

**Frontend change:** after a successful Save, fire a follow-up call to `/api/save-snapshot` with
the same holdings payload. If it fails, show a toast (e.g. "Saved, but snapshot failed: <reason>")
— this must never block or roll back the already-successful Save.

## PDF Content

One table, one row per position, columns: Ticker, Name, Score, Tier, P&L $, P&L %, Action,
Momentum. Sorted by score descending, matching the existing Rankings tab order. A summary line
above the table: total value, total invested, total P&L, generation timestamp.

Main and trial positions are both included, in two separate tables (mirroring the existing
Rankings/Trials tab split), trial positions clearly labeled.

## Error Handling

- **Scoring fails** (e.g. yfinance unreachable): `/api/save-snapshot` returns a JSON error;
  no PDF is written, no partial/corrupt file is left behind.
- **No valid holdings** (empty portfolio): mirrors `run_scoring`'s existing behavior — returns
  the same `{"error": "No valid holdings..."}` shape, no PDF generated.
- **`reports/` directory missing**: created automatically on first snapshot; this is not an
  error condition.

## Testing

- Unit test the PDF-rendering function in isolation: given a fixed, synthetic `run_scoring()`-shaped
  result dict, confirm a PDF file is written, is non-empty, and is valid PDF (starts with the
  `%PDF-` magic bytes) — without needing real scoring data or network access.
- Unit test `/api/save-snapshot`'s error path: monkeypatch `run_scoring` to return an error dict,
  confirm no file is written and the route returns the error.
- Manual check: click Save in the running app, confirm `reports/portfolio_report_<today>.pdf`
  exists and opens correctly, and that saving again the same day overwrites rather than
  duplicating.

## Explicitly Out of Scope

- Historical report browsing/listing UI (just a flat dated file on disk for now).
- Excel import on first load (separate deferred item, unrelated to this).
- Configurable report content/columns.
