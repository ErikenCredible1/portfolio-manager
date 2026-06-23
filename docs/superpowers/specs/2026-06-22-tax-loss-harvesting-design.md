# Tax-Loss Harvesting (Phase 3b)

## Goal

Recommend a set of currently-losing positions to sell in December, up to the $3,000/year
capital-loss deduction limit, while tracking realized sales throughout the year (so the
December target accounts for losses already taken) and warning about wash-sale risk if a
recently-harvested ticker gets re-added to holdings too soon.

## Background

Phase 3 in the original plan bundled max-position limits with tax-loss harvesting. These are
unrelated in mechanism, so they were split into two specs (Phase 3a, already complete, covered
max-position limits; this is Phase 3b).

A real gap surfaced during brainstorming: this app has no memory of *realized* gains/losses —
it only computes live unrealized P&L for currently-held positions. Once a position is fully
sold (main or trial), it disappears from `run_scoring()`'s loop with no record. A loss realized
outside the app's harvest flow (e.g. a March sale, for any reason) would otherwise be invisible
to the December $3k target. This spec adds a manual realized-sale log to close that gap.

## Architecture & Data Flow

**New state file**, `realized_sales.json`:

```json
{"sales": [{"ticker": "XYZ", "amount": -450.0, "date": "2026-03-15T10:00:00", "pos_type": "main"}]}
```

Entries accumulate indefinitely; filtering by year or by the 31-day wash-sale window happens at
read-time against the full log, not by pruning old entries.

Two ways an entry gets added:
1. **One-click, on a recommended December candidate**: the app already knows a held position's
   exact unrealized loss, so a "Mark as Harvested" button on a recommendation logs
   ticker/amount/pos_type immediately, with today's date.
2. **A small manual form, visible year-round** (not December-gated): ticker, dollar amount,
   main/trial — for any sale outside the recommendation flow.

Two new read functions:
- `realized_losses_this_year()` — sums negative-`amount` entries whose `date` falls in the
  current calendar year. Returns 0 if there are none.
- `wash_sale_clear_date_for(ticker)` — looks at the *most recent* log entry for that ticker
  (if multiple exist, e.g. sold/rebought/sold again over time); if it's within the last 31
  days, returns the date 31 days after it; otherwise `None`.

The wash-sale check only ever fires for tickers present in the current holdings *input* — a
fully-sold ticker isn't in `run_scoring()`'s loop at all until it's typed back in, so this is
the only point where a rebuy-risk can actually be surfaced. This is an inherent limitation of a
tool that doesn't execute trades, not something this design can close: it can't warn about a
rebuy that already happened outside the app.

## December Recommendation Algorithm

Gated by a small standalone function, `is_harvest_month()` (`datetime.now().month == 12`),
kept separate from the rest of the logic specifically so tests can monkeypatch it directly
rather than mocking `datetime` itself.

The target is reduced by losses already logged this calendar year:

```python
remaining_target = max(0, 3000 - abs(realized_losses_this_year()))
```

Among all currently-held positions (main + trial) with `pnl < 0`, sort by loss size descending
and greedily accumulate: include a position if `running_total + abs(pnl) <= remaining_target`;
otherwise skip it and continue checking smaller losses further down the list (a smaller loss
may still fit even when a larger one didn't). This is a simple greedy fill, not an exact
subset-sum optimization — consistent with how the rest of this app favors simple heuristics
(e.g. the existing softmax allocation) over exact optimization.

If `remaining_target` is 0 (already realized $3k+ this year) or there are no losing positions,
the candidate list is empty — not an error, just nothing to recommend.

Each selected position gets `tax_harvest_candidate: true` in `run_scoring()`'s output; every
other position (including all positions in any non-December month) gets `false`.

## Wash-Sale Field

For every position in the current holdings input (main or trial), `run_scoring()` calls
`wash_sale_clear_date_for(ticker)` and sets `wash_sale_clear_date` (an ISO date string or
`null`) on that position. This is fully independent of `momentum_signal`/`action`/
`over_position_cap` — a re-added ticker can simultaneously show `BUY` from the scoring engine
(which has no concept of tax history) while carrying an active `wash_sale_clear_date`. Both
facts stay separately visible, the same precedent set by every other signal field in this app.

## UI

A new `[ TAX HARVEST ]` tab, always present in the tab bar:

- **December only**: a table of recommended candidates (Ticker, Name, Tier, P&L $, a running
  cumulative-toward-target column, "Mark as Harvested" button per row), with a header line
  showing the computed target (e.g. "Target: $1,840 remaining of $3,000 — $1,160 already
  realized this year").
- **Year-round**: a small manual log form (Ticker, Amount, Main/Trial dropdown, "Log Sale"
  button).
- **Year-round**: a "Currently Wash-Sale Restricted" list — any ticker in your current holdings
  input with an active `wash_sale_clear_date`, showing when it clears. A short static explainer
  line above this section: *"Wash sale rule: if you rebuy the same ticker within 30 days before
  or after a tax-loss sale, the IRS disallows that loss for this year's taxes. Wait until the
  clear date below before repurchasing."*
- Outside December, if there's nothing to show in either the recommendation or restriction
  section: "No tax-loss harvesting candidates this month — recommendations appear in December,"
  with the log form still available below it.

"Mark as Harvested" calls `POST /api/log-sale` with the position's current ticker/pnl/pos_type
pre-filled, then removes that row from the recommendation table (optimistic UI, same pattern as
the Watchlist's "Remove" button) — it does not touch your holdings/shares.

## Error Handling

- **No losing positions in December, or `remaining_target` already 0**: empty candidate list,
  clear "nothing to harvest" UI message, not an error.
- **`wash_sale_clear_date_for` with no log history for a ticker**: returns `None` cleanly.
- **Multiple log entries for the same ticker**: the most recent one governs wash-sale status —
  that's the constraint that actually matters going forward.
- **Year rollover**: `realized_losses_this_year()` filters strictly by the current calendar
  year, so a loss logged last December doesn't count toward this year's target.

## Testing

- `log_realized_sale`/`load_realized_sales` round-trip.
- `realized_losses_this_year()`: sums this-year losses correctly; excludes prior-year entries;
  excludes positive (gain) entries.
- `wash_sale_clear_date_for()`: returns a date within the 31-day window; `None` if no entry or
  entry older than 31 days; uses the most recent entry when several exist for the same ticker.
- Greedy selection: a scenario constructed so a larger loss must be skipped (would overshoot
  the target) while a smaller one further down the list still fits — proving a real fill, not
  naive stop-on-first-miss.
- `run_scoring()`'s December gate: with `is_harvest_month()` mocked `True`, candidates flag
  correctly; mocked `False`, nothing is ever flagged regardless of losses.
- `/api/log-sale` route: writes an entry, verifiable afterward via `realized_losses_this_year()`
  /`wash_sale_clear_date_for()`.
- Frontend: no automated test (embedded HTML/JS); manual verification via the same curl-based
  structural check plus an actual browser run-through used in every prior phase.

## Explicitly Out of Scope (this phase)

- Auto-detecting sales by diffing holdings between Saves (manual log only, per design decision).
- Exact subset-sum optimization for the $3k target (greedy fill only).
- Full capital gains/losses netting across the whole year (only losses are tracked toward the
  $3k target; realized gains are not netted against it).
- Phase 4 (monthly automation + email).
