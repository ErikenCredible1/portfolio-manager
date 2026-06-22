# Watchlist & Re-Entry System (Phase 2)

## Goal

Turn the minimal repeat-offender timestamp Phase 1 introduced into a real watchlist: a visible
tab showing currently-trimmed positions, a distinct re-entry signal when a watchlisted ticker
recovers, and a way to dismiss a ticker once you've actually re-entered it. This is Phase 2 of
the 4-phase rebuild scoped during the Phase 1 brainstorm.

## Background

Phase 1 already built most of the underlying machinery:

- `watchlist_state.json` stores `{"flagged": {ticker: iso_timestamp}}` — when a ticker first
  triggered `TRIM_TO_100`.
- `is_watchlisted(ticker)` / `watchlisted_since(ticker)` / `flag_watchlisted(ticker)` read and
  write that state.
- `evaluate_momentum_signal(ticker, score, technicals)` already returns `BUY` when score ≥ 70
  and ≥2-of-3 technicals are bullish — which happens to be exactly the re-entry criteria
  originally specified for this phase. It does this unconditionally, regardless of whether the
  ticker is currently watchlisted.

What's missing is visibility (no UI surfaces the watchlist at all), distinction (a recovered
watchlisted ticker looks identical to any other new BUY idea), and clearing (nothing ever
removes a ticker from `flagged` once added).

Explicitly out of scope for this phase (per the original Phase 1 brainstorm and confirmed again
here): computing the actual share/dollar amount to sell for `TRIM_TO_100` — it stays a label,
not an executed trade calculation. Max-position limits and tax-loss harvesting are Phase 3.
Automation/email is Phase 4.

## Architecture & Data Flow

`run_scoring()` gains one new field per position: `"watchlisted_since"` — the ISO timestamp
string if the ticker is currently flagged, `null` otherwise. This rides the same response
`/api/score` already returns; no new GET endpoint is needed. The new Watchlist tab is populated
entirely client-side by filtering that same response: `positions.filter(p => p.watchlisted_since)`.

One new write path: `POST /api/unwatch`, accepting `{"ticker": "<str>"}`, which removes that
ticker from `watchlist_state.json`'s `flagged` dict via a new `unflag_watchlisted(ticker)`
function. This mirrors the existing decoupled-write pattern `flag_watchlisted` already
established — a small, focused state mutation independent of the scoring response cycle.

## Re-Entry Signal Logic

`evaluate_momentum_signal()` gets one new check inside its existing BUY branch: when score ≥ 70
and ≥2-of-3 technicals are bullish, check `is_watchlisted(ticker)`. If true, return `"RE_ENTRY"`
instead of `"BUY"`. Every other branch (the `score < 30` sell path, the 3-day FULL_SELL gating,
the fallback to `HOLD`) is unchanged.

`momentum_signal` becomes a 5-value field: `BUY / RE_ENTRY / FULL_SELL / TRIM_TO_100 / HOLD`.
`RE_ENTRY` gets its own CSS color in the green family (it's fundamentally a bullish signal) but
visually distinguishable from plain `BUY` — the exact shade is an implementation detail chosen
to read clearly against the current palette, not a design requirement.

## Watchlist Tab

A new `[ WATCHLIST ]` tab, positioned after `[ TRIALS ]` in the existing tab bar. Table columns:

- Ticker, Name, Score, Tier (same as other tables, for context)
- Flagged Date (human-readable date from `watchlisted_since`)
- Days Until Eligible — counts down from `MIN_DAYS_BEFORE_FULL_SELL` (3), shows "Eligible" once
  it reaches 0 (i.e., once a `FULL_SELL` signal could fire on the next trigger)
- Momentum Signal (will typically read `HOLD`, `FULL_SELL`, or `RE_ENTRY` for a watchlisted row)
- A "Remove" button

If no positions are currently watchlisted, the tab shows the same empty-state pattern already
used elsewhere in the app (e.g. "No positions on the watchlist").

The "Remove" button calls `POST /api/unwatch` with that ticker, then removes the row from the
table immediately (optimistic UI) rather than triggering a full re-score — dismissing doesn't
change the position's actual score or value, so there's nothing to recompute.

## Backend Additions

```python
def unflag_watchlisted(ticker):
    state = load_watchlist_state()
    flagged = state.get("flagged", {})
    flagged.pop(ticker, None)
    state["flagged"] = flagged
    save_watchlist_state(state)
```

```python
@app.route("/api/unwatch", methods=["POST"])
def api_unwatch():
    ticker = request.json.get("ticker", "")
    unflag_watchlisted(ticker)
    return jsonify({"ok": True})
```

Placed alongside the existing watchlist functions and routes, following the patterns Phase 1
already established (`flag_watchlisted` for the function, `/api/save-snapshot` for the
decoupled-route style).

## Error Handling

- **Unflagging a ticker that isn't flagged**: `dict.pop(ticker, None)` is already a no-op —
  no error, idempotent, matching `flag_watchlisted`'s existing idempotency guarantee.
- **Missing/empty `ticker` in the unwatch request**: `unflag_watchlisted("")` is harmless (no
  entry will ever match an empty string), so no special-casing is needed.
- **`RE_ENTRY` evaluated for a ticker with no watchlist history**: falls through to the existing
  `is_watchlisted` check, which correctly returns `False` — no behavior change for any
  never-watchlisted ticker hitting the BUY threshold.

## Testing

- `unflag_watchlisted`: flagging then unflagging clears `is_watchlisted`; unflagging a
  never-flagged ticker doesn't raise.
- `evaluate_momentum_signal`'s new branch: a watchlisted ticker hitting the BUY threshold
  returns `RE_ENTRY`, not `BUY`; a non-watchlisted ticker at the same threshold still returns
  plain `BUY` (regression check against Phase 1 behavior).
- `/api/unwatch` route: confirms `is_watchlisted` is `False` after the call, via Flask's
  `test_client()`.
- `run_scoring()`: confirms `watchlisted_since` appears correctly (timestamp vs. `null`) per
  position.
- Frontend: no automated test (embedded HTML/JS); manual verification via a curl-based
  structural check plus an actual run-through in the browser, same pattern as Phase 1's
  frontend task.

## Explicitly Out of Scope (this phase)

- Computing actual trim trade size (shares/dollars to sell for `TRIM_TO_100`).
- Max-position limits, tax-loss harvesting (Phase 3).
- Monthly automation, email reports (Phase 4).
- Auto-clearing the watchlist flag based on detected share-count changes (manual dismiss only).
