# Max-Position Cap (Phase 3a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flag the lowest-scoring main positions for full exit once the portfolio holds more
than 35 names.

**Architecture:** A new boolean field, `over_position_cap`, computed in `run_scoring()` by
ranking main-only positions by score and flagging everything beyond the cap. Surfaced as a new
"Cap" column in the Rankings table only — independent of the existing `action` and
`momentum_signal` fields, not overriding either.

**Tech Stack:** Flask, pandas (existing — no new dependencies).

## Global Constraints

- `MAX_MAIN_POSITIONS = 35` — a hardcoded module constant, not user-configurable.
- `over_position_cap` is computed from main positions (`pos_type != "trial"`) only. Trial
  positions are never flagged, regardless of their score.
- Ranking is by the existing `score` field, descending. Only positions beyond the top
  `MAX_MAIN_POSITIONS` (by that ranking) are flagged `True`; everyone else is `False`.
- This field does not affect or override `action` or `momentum_signal` in any way — a position
  can be `BUY` and `over_position_cap: true` simultaneously.
- No actual trade size is computed for this signal (consistent with `TRIM_TO_100`'s existing
  behavior) — it's a flag, not an executed recommendation.
- Tests run from the project root with: `python3 -m pytest tests/ -v`

---

## File Structure

- **Modify:** `portfolio_app.py` — `MAX_MAIN_POSITIONS` constant, the `over_position_cap`
  computation inside `run_scoring()`, and the frontend HTML/CSS/JS for the new "Cap" column
  (Rankings table only).
- **Create:** `tests/test_position_cap.py`

---

### Task 1: `over_position_cap` computation in `run_scoring()`

**Files:**
- Create: `tests/test_position_cap.py`
- Modify: `portfolio_app.py` (add `MAX_MAIN_POSITIONS` constant near `MIN_DAYS_BEFORE_FULL_SELL`;
  add the ranking/flagging step inside `run_scoring`)

**Interfaces:**
- Consumes: nothing new — uses the existing `df["score"]`, `df["pos_type"]`, `df["ticker"]`
  columns already present in `run_scoring`'s DataFrame by this point.
- Produces: every position in `run_scoring()`'s output gains `"over_position_cap": bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_position_cap.py`:

```python
import portfolio_app


def _technicals_neutral(ticker):
    return {"macd": "neutral", "ma50": "neutral", "rsi_failure_swing": "neutral"}


def test_run_scoring_flags_lowest_scoring_positions_beyond_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    scores = {f"T{i}": float(i) for i in range(1, 37)}  # T1..T36, scores 1..36

    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (scores[ticker], "Medium", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": f"T{i}", "shares": "1", "invested": "100", "type": "main"}
        for i in range(1, 37)
    ]
    result = portfolio_app.run_scoring(holdings)
    by_ticker = {p["ticker"]: p for p in result["positions"]}

    assert by_ticker["T1"]["over_position_cap"] is True    # lowest score, 1 over the cap of 35
    assert by_ticker["T2"]["over_position_cap"] is False    # rank 35 from the top, just inside
    assert by_ticker["T36"]["over_position_cap"] is False   # highest score


def test_run_scoring_does_not_flag_anyone_at_or_under_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    scores = {f"T{i}": float(i) for i in range(1, 36)}  # T1..T35, exactly at the cap

    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (scores[ticker], "Medium", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": f"T{i}", "shares": "1", "invested": "100", "type": "main"}
        for i in range(1, 36)
    ]
    result = portfolio_app.run_scoring(holdings)

    assert all(p["over_position_cap"] is False for p in result["positions"])


def test_run_scoring_never_flags_trial_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    # 36 main positions (scores 1..36) plus one trial position with the lowest score of all --
    # the trial position must never be flagged, even though it would rank last overall.
    scores = {f"T{i}": float(i) for i in range(1, 37)}
    scores["TRIAL1"] = 0.0

    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (scores[ticker], "Medium", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": f"T{i}", "shares": "1", "invested": "100", "type": "main"}
        for i in range(1, 37)
    ] + [{"ticker": "TRIAL1", "shares": "1", "invested": "100", "type": "trial"}]

    result = portfolio_app.run_scoring(holdings)
    by_ticker = {p["ticker"]: p for p in result["positions"]}

    assert by_ticker["TRIAL1"]["over_position_cap"] is False
    assert by_ticker["T1"]["over_position_cap"] is True  # lowest-scoring main position instead
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_position_cap.py -v`
Expected: FAIL with `KeyError: 'over_position_cap'`

- [ ] **Step 3: Implement the cap computation**

In `portfolio_app.py`, find `MIN_DAYS_BEFORE_FULL_SELL = 3  # approximated as calendar days, not trading days`
and add directly after it:

```python
MAX_MAIN_POSITIONS = 35
```

Find this line inside `run_scoring`:

```python
    df["action"] = df["trade_value"].apply(compute_action)
```

and the line directly after it:

```python
    df = df.sort_values("score", ascending=False).reset_index(drop=True)
```

Insert a new step between them:

```python
    df["action"] = df["trade_value"].apply(compute_action)

    main_mask   = df["pos_type"] != "trial"
    main_ranked = df[main_mask].sort_values("score", ascending=False)
    excess      = set(main_ranked.iloc[MAX_MAIN_POSITIONS:]["ticker"]) if len(main_ranked) > MAX_MAIN_POSITIONS else set()
    df["over_position_cap"] = df["ticker"].isin(excess)

    df = df.sort_values("score", ascending=False).reset_index(drop=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_position_cap.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests, including everything from Phases 1-2)

- [ ] **Step 6: Commit**

```bash
git add tests/test_position_cap.py portfolio_app.py
git commit -m "feat: flag lowest-scoring main positions beyond the 35-position cap"
```

---

### Task 2: "Cap" column in the Rankings table (frontend)

**Files:**
- Modify: `portfolio_app.py` (CSS rule, Rankings table header, Rankings row template, all
  within the `HTML_PAGE` string)

**Interfaces:**
- Consumes: `over_position_cap` (Task 1).
- No new Python interfaces — this is frontend HTML/CSS/JS, and only touches the Rankings table
  (not Trials — trial positions are never flagged, so that table doesn't need this column).

- [ ] **Step 1: Add a CSS rule for the new badge**

Find the existing momentum-signal CSS rules and add, directly after `.TRIM_TO_100`:

```css
  .OVER_CAP { color: var(--red); font-weight: 900; }
```

- [ ] **Step 2: Add the "Cap" column header to the Rankings table only**

Find the Rankings table's header row — it's the one whose `<thead>` is immediately followed by
`<tbody id="rankBody"></tbody>` (the Trials table has an identical-looking header but its
`<tbody>` is `id="trialsBody"` — make sure you're editing the Rankings one). Replace:

```html
            <th>Action</th><th>Momentum</th>
```

with:

```html
            <th>Action</th><th>Momentum</th><th>Cap</th>
```

Do NOT make this change to the Trials table's header (the one followed by
`<tbody id="trialsBody"></tbody>`) — leave it exactly as is.

- [ ] **Step 3: Add the "Cap" cell to the Rankings row template**

Find the Rankings row template — it's the one whose closing line is
`'<tr><td colspan="16" class="empty">No main positions scored</td></tr>'`. Replace:

```js
      <td><span class="action ${p.momentum_signal}">${p.momentum_signal}</span></td>
    </tr>`;
  }).join('') || '<tr><td colspan="16" class="empty">No main positions scored</td></tr>';
```

with:

```js
      <td><span class="action ${p.momentum_signal}">${p.momentum_signal}</span></td>
      <td>${p.over_position_cap ? '<span class="action OVER_CAP">OVER CAP</span>' : ''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="17" class="empty">No main positions scored</td></tr>';
```

Do NOT touch the Trials row template (the one ending in
`'<tr><td colspan="12" class="empty">No trial positions scored</td></tr>'`) — trial positions
never carry this badge, so that table stays unchanged.

- [ ] **Step 4: Run the full pytest suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (this is a frontend-only change; confirms no regressions)

- [ ] **Step 5: Manually verify in the browser**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 portfolio_app.py`

In the browser that opens:
1. Load your holdings and click Score.
2. Confirm the Rankings tab now shows a "Cap" column, and the Trials tab does NOT have one.
3. If you currently hold 35 or fewer main positions, confirm the Cap column is blank for every
   row (no `OVER CAP` badges) — this is the expected/normal case for most portfolios.
4. If you want to see the badge actually fire, you can temporarily lower `MAX_MAIN_POSITIONS` in
   the code to a small number (e.g. `3`) to confirm `OVER CAP` badges render correctly styled
   (red, bold) on your lowest-scoring rows, then change it back to `35` before committing
   anything further.

Stop the server with Ctrl+C when done.

- [ ] **Step 6: Commit**

```bash
git add portfolio_app.py
git commit -m "feat: display OVER CAP badge in Rankings table"
```

---

## Self-Review

**Spec coverage:** `MAX_MAIN_POSITIONS` constant, main-only ranking, lowest-scorers-beyond-cap
flagging (Task 1) ✓. Independent field, no override of `action`/`momentum_signal` (Task 1,
verified by the design itself — the new field is additive, nothing else changes) ✓. Rankings-only
UI surface, new CSS rule (Task 2) ✓. Error handling (fewer than 36 positions, ties, zero main
positions) is covered implicitly — the `set()`/`isin()` approach naturally produces an empty
`excess` set in all three cases, and Task 1's tests exercise the at-cap and under-cap cases.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `over_position_cap` is a plain Python `bool` produced by
`df["ticker"].isin(excess)` (pandas boolean Series → Python `bool` after `to_dict`), consistent
between Task 1's implementation and Task 2's frontend check (`p.over_position_cap ? ... : ''`,
a truthy/falsy JS check that works correctly against a JSON `true`/`false`).
