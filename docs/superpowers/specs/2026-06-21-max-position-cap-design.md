# Max-Position Cap (Phase 3a)

## Goal

Flag the lowest-scoring main positions for full exit once the portfolio holds more than 35
names, so the position count stays manageable. This is the first half of Phase 3 from the
original 4-phase rebuild plan; the second half (tax-loss harvesting) is unrelated in mechanism
and scoped as its own separate brainstorm round.

## Background

Phase 3 in the original plan bundled max-position limits with December tax-loss harvesting.
These are independent subsystems — one is a portfolio-construction/sizing concern, the other a
tax-calendar/wash-sale concern — so they're split into two specs, each with its own
brainstorm → spec → plan cycle, the same way Phase 1's momentum/technicals work and Phase 2's
watchlist/re-entry work were kept separate despite both originating from the same original
phase grouping.

This spec covers only the position-count cap.

## Architecture & Computation

A new module-level constant, `MAX_MAIN_POSITIONS = 35`, placed alongside the existing threshold
constants (`MIN_DAYS_BEFORE_FULL_SELL`, etc.).

Inside `run_scoring()`, after the existing `action` column is computed and before the final
`df.sort_values("score", ascending=False)` call, a new step:

```python
main_mask   = df["pos_type"] != "trial"
main_ranked = df[main_mask].sort_values("score", ascending=False)
excess      = set(main_ranked.iloc[MAX_MAIN_POSITIONS:]["ticker"]) if len(main_ranked) > MAX_MAIN_POSITIONS else set()
df["over_position_cap"] = df["ticker"].isin(excess)
```

Trial positions are excluded from `main_ranked` entirely, so they can never be flagged
regardless of their score. Every position in `run_scoring()`'s output gains one new boolean
field: `over_position_cap`.

This is deliberately a separate, independent field from the existing `action` (weight-based
rebalancing) and `momentum_signal` (technical/momentum-based) fields — the same separation of
concerns established in Phase 1 and Phase 2. A position can simultaneously show `BUY` and be
`over_position_cap: true`; neither field overrides the other, so the distinct reasons for a
recommendation stay independently visible. Like `TRIM_TO_100`, this does not compute the actual
trade size to execute — just a flag that this position is a candidate for full exit because the
portfolio is over the cap.

## UI

A new "Cap" column in the **Rankings** table only (not Trials, since trial positions are never
flagged there). Renders a badge only when set:

```js
<td>${p.over_position_cap ? '<span class="action OVER_CAP">OVER CAP</span>' : ''}</td>
```

A new CSS rule `.OVER_CAP`, in the red family (it's fundamentally a sell recommendation) but
visually distinct from `.FULL_SELL`/`.TRIM` so the reason for the flag is identifiable at a
glance.

No new summary metric in the top metrics row, no dedicated tab — kept minimal, consistent with
how `RE_ENTRY`/`FULL_SELL` don't have their own summary counters either.

## Error Handling

- **Fewer than 36 main positions**: `excess` is an empty set; every position's
  `over_position_cap` is `False`. Falls out of the existing logic naturally, no special-casing.
- **All main positions tied at the same score**: `sort_values` is stable, ties resolve by
  original row order — deterministic, no crash, no tiebreaker rule needed.
- **Zero main positions (all trial)**: `main_ranked` is empty; `len(main_ranked) > MAX_MAIN_POSITIONS`
  is `False`; `excess` stays empty. No division-by-zero or indexing error.

## Testing

- `run_scoring()` with 36+ main positions: only the lowest-scoring position(s) beyond the cap
  are flagged `True`; the rest are `False`.
- `run_scoring()` with 35 or fewer main positions: every position is `False`.
- A mixed main+trial portfolio over the main-cap: trial positions are never flagged regardless
  of score, even when their score is lower than every main position's.
- Frontend: no automated test (embedded HTML/JS). Manual verification via the same curl-based
  structural check plus an actual browser run-through used in every prior phase.

## Explicitly Out of Scope (this spec)

- Tax-loss harvesting (separate future brainstorm round).
- Computing actual trade size (shares/dollars) for the recommended exit.
- A dedicated "Over Cap" tab or summary metric.
- Making `MAX_MAIN_POSITIONS` user-configurable (hardcoded constant, matching the existing
  pattern for `MIN_DAYS_BEFORE_FULL_SELL`).
