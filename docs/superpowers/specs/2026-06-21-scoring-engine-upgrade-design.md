# Scoring Engine Upgrade (Phase 1 of portfolio rebuild)

## Goal

Replace the current momentum weighting in `score_asset()` with a shorter-horizon scheme, add
technical-indicator confirmation (MACD, 50-day MA, RSI failure swing), and surface a clear
per-position momentum signal (BUY / FULL_SELL / TRIM_TO_100 / HOLD) — separate from the existing
weight-based rebalancing signal.

This is Phase 1 of a 4-phase rebuild (watchlist & re-entry, position limits + tax-loss harvesting,
and automation/email come later as their own design docs). The major gaps this phase addresses:

- No momentum-based sell signal
- Momentum weighting is stale (1m/6m/12m, no 1-week or 3-month component)
- No technical-indicator confirmation on signals

Out of scope for this phase (deferred to later rounds): watchlist persistence beyond a minimal
flag, max-position enforcement, tax-loss harvesting, monthly automation/email, Excel import on
first load, dated save snapshots.

## Architecture & Data Flow

Current flow: `run_scoring(holdings)` (portfolio_app.py:324) loops over holdings, calls
`score_asset(ticker)` for each, builds a DataFrame, and runs `target_allocation()`. The
`/api/score` route is pure computation — it never writes to disk; only the explicit `/api/save`
route persists holdings. This separation is preserved.

New pieces:

- `score_asset(ticker)` — internals updated with the new momentum weights (see below). Signature
  unchanged: still returns `(score, tier, sector, live_price)`, so nothing downstream breaks.
- `get_technicals(ticker)` — new function. Computes MACD, 50-day MA position, and RSI failure
  swing in one pass per ticker and caches the result, mirroring the existing `_price_cache` /
  `_info_cache` / `_sector_ret_cache` pattern (portfolio_app.py:74-76). Both this phase's signal
  check and Phase 2's re-entry check will read from this same cached snapshot.
- `evaluate_momentum_signal(ticker, score, technicals)` — new function returning
  `BUY` / `FULL_SELL` / `TRIM_TO_100` / `HOLD`.
- `run_scoring()` calls `get_technicals()` and `evaluate_momentum_signal()` per position and adds
  a `momentum_signal` field to each position in the JSON response, alongside the existing
  (renamed) `action` field.

**Repeat-offender state:** deciding `FULL_SELL` vs `TRIM_TO_100` requires remembering whether a
ticker has been trimmed before. `/api/score` never writes to the user's holdings data (it's
recomputed on every price refresh, not just on explicit Save) — that rule is preserved, and this
flag must not be added to the regular holdings data the user manually edits and saves. Instead, it
gets its own small separate file, `watchlist_state.json`, written directly by the backend the
moment a fresh `TRIM_TO_100` fires. This is system-tracked state, not user data — a narrow,
deliberate exception to "score requests don't write," and it's the seed of the full watchlist
system Phase 2 will build out.

## Momentum Scoring Changes

Replacing the current 1m/6m/12m momentum block in `score_asset()` (portfolio_app.py:227-235):

| Period   | Trading days | Weight | Clip range    |
|----------|--------------|--------|----------------|
| 1 week   | 5            | 10%    | ±5%            |
| 1 month  | 21           | 35%    | ±10%           |
| 3 months | 63           | 40%    | -15% / +18%    |
| 6 months | 126          | 15%    | -15% / +20%    |

The 12-month return is dropped entirely. Clip ranges scale with the horizon (a 5% weekly move is
already extreme; a 6-month move has more room before it's extreme). These are starting constants,
easy to retune after seeing real output.

The existing `* 3.5` scale-up factor (which maps the weighted momentum average onto its point
contribution to the 0-100 score) is kept unchanged, so momentum's overall weight relative to
fundamentals/volatility/volume in the total score doesn't shift — only the timeframes/weights
within the momentum component change.

## Technical Indicators

Computed once per ticker inside `get_technicals()`:

**MACD (12/26/9 EMA, standard):** `macd_line = EMA(12) - EMA(26)` of close price;
`signal_line = EMA(9)` of `macd_line`. Bullish if `macd_line > signal_line`, bearish if below.

**50-day moving average:** Bullish if current price > 50-day MA, bearish if below.

**RSI failure swing (Wilder, 14-period RSI):** A pattern, not a threshold, checked over the
trailing ~20 trading days:
- Bearish failure swing: RSI rises above 70, pulls back below 70, rises again but fails to
  exceed its prior peak, then turns down. Confirms a topping reversal.
- Bullish failure swing: mirror image — RSI falls below 30, bounces back above 30, falls again
  but fails to make a new low, then turns up. Confirms a bottoming reversal.
- If no such pattern appears in the lookback window, returns `neutral` — counts toward neither
  side of the 2-of-3 vote. Failure swings are relatively rare, so MACD and 50-MA will be the
  more frequently-firing confirmations in practice.

## Signal Logic (two independent concepts)

There are two unrelated kinds of "trim" in this system, surfaced as two separate fields:

**`action`** (existing field, portfolio_app.py:367-369, renamed only — no logic change):
`BUY / TRIM / HOLD`. Driven by `trade_value` (current weight vs. target weight). This is a sizing
correction — "TRIM" replaces the old "SELL" label since it's rarely a full exit (tier floors keep
a minimum weight). Renamed for clarity now that a second, unrelated signal exists.

**`momentum_signal`** (new field): `BUY / FULL_SELL / TRIM_TO_100 / HOLD`. Driven by score +
technicals, independent of position size:

- **BUY**: score ≥ 70 *and* ≥2 of 3 technicals bullish (same bar Phase 2 will reuse for
  re-entry, keeping the "strong bullish confirmation" threshold consistent system-wide)
- **TRIM_TO_100**: score < 30 *and* ≥2 of 3 technicals bearish, *and* the ticker is not yet
  flagged in `watchlist_state.json` — first-time trigger, trim to a $100 token holding rather
  than a full exit, then flag the ticker.
- **FULL_SELL**: same trigger condition, but the ticker is already flagged in
  `watchlist_state.json` (i.e., it already failed once before) — full exit.
- **HOLD**: everything else, including cases where the score is extreme but technicals don't
  confirm (a deliberate "wait for confirmation" gap, not a bug).

Both fields appear side by side per position: `action` answers "is your position sized right,"
`momentum_signal` answers "is the stock's momentum strong or weak."

## Error Handling

Following the existing pattern in `score_asset()`, which already falls back to a default when
price history is too short (portfolio_app.py:221-222):

- **Insufficient history** (new IPO, <50 days of data): MACD / 50-MA / RSI each individually fall
  back to `neutral` rather than raising.
- **All-neutral technicals**: naturally resolves to `HOLD` (BUY/SELL both require 2-of-3
  confirmation, so zero confirmations defaults safely to no-signal) — no extra special-casing
  needed.
- **`watchlist_state.json` missing on first run**: load helper returns an empty dict, mirroring
  how `load_data()` already falls back gracefully when `portfolio_data.json` doesn't exist.
- **yfinance failures**: same try/except-and-fall-back-to-empty pattern already used in
  `get_price_history()`.

## Testing

The old-vs-new momentum weighting comparison has already been run and validated by the user
outside this process. As part of implementation, do a small correctness spot-check: hand-calculate
the new momentum formula for 2-3 tickers from actual current holdings and confirm the code's
output matches, before trusting it on the full portfolio. This is a verification step, not a
deliverable feature.

## Explicitly Out of Scope (this phase)

- Watchlist UI / full re-entry logic (Phase 2)
- Max-position enforcement, tax-loss harvesting (Phase 3)
- Monthly automation, email reports (Phase 4)
- Excel import on first load, dated save snapshots (separate future brainstorm — unrelated to
  scoring logic)
