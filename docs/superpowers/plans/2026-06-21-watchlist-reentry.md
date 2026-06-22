# Watchlist & Re-Entry System (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Phase 1's minimal repeat-offender timestamp into a real watchlist: a visible tab,
a distinct re-entry signal when a watchlisted ticker recovers, and a manual dismiss action.

**Architecture:** Extend the existing `run_scoring()` → `/api/score` → frontend data flow with
two new per-position fields (`watchlisted_since`, `days_until_eligible`) rather than adding a
separate GET endpoint. Add one new decoupled write path (`/api/unwatch`) mirroring the existing
`flag_watchlisted`/`/api/save-snapshot` pattern from Phase 1.

**Tech Stack:** Flask, pytest (existing — no new dependencies this phase).

## Global Constraints

- `momentum_signal` becomes a 5-value field: `BUY / RE_ENTRY / FULL_SELL / TRIM_TO_100 / HOLD`.
- `RE_ENTRY` fires instead of `BUY` when score ≥ 70, ≥2-of-3 technicals bullish, AND the ticker
  is currently watchlisted (`is_watchlisted(ticker)` is `True`). All other thresholds unchanged.
- New position fields from `run_scoring()`: `watchlisted_since` (ISO timestamp string or `null`),
  `days_until_eligible` (integer countdown from `MIN_DAYS_BEFORE_FULL_SELL`, or `null` if not
  watchlisted).
- `unflag_watchlisted(ticker)` must be idempotent (unflagging a never-flagged ticker must not
  raise).
- `POST /api/unwatch` accepts `{"ticker": "<str>"}`, always returns `{"ok": true}` with status
  200 (idempotent regardless of whether the ticker was actually flagged).
- Out of scope this phase: computing actual trim trade size for `TRIM_TO_100`, auto-clearing the
  watchlist flag based on share-count changes (manual dismiss only).
- Tests run from the project root with: `python3 -m pytest tests/ -v`

---

## File Structure

- **Modify:** `portfolio_app.py` — `unflag_watchlisted` function, `evaluate_momentum_signal`'s
  new branch, `run_scoring()`'s two new fields, the `/api/unwatch` route, and the frontend
  HTML/CSS/JS for the new Watchlist tab.
- **Modify:** `tests/test_watchlist_state.py` — append `unflag_watchlisted` tests.
- **Modify:** `tests/test_momentum_signal.py` — append `RE_ENTRY` tests.
- **Modify:** `tests/test_run_scoring.py` — append `watchlisted_since`/`days_until_eligible` tests.
- **Create:** `tests/test_unwatch_route.py`

---

### Task 1: `unflag_watchlisted()`

**Files:**
- Modify: `tests/test_watchlist_state.py` (append)
- Modify: `portfolio_app.py` (insert after `flag_watchlisted`, before `evaluate_momentum_signal`)

**Interfaces:**
- Consumes: `load_watchlist_state`, `save_watchlist_state` (existing, Phase 1).
- Produces: `unflag_watchlisted(ticker: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_watchlist_state.py`:

```python
def test_unflag_watchlisted_clears_is_watchlisted(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    flag_watchlisted("NVDA")
    assert is_watchlisted("NVDA") is True
    portfolio_app.unflag_watchlisted("NVDA")
    assert is_watchlisted("NVDA") is False


def test_unflag_watchlisted_on_never_flagged_ticker_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    portfolio_app.unflag_watchlisted("NVDA")
    assert is_watchlisted("NVDA") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_watchlist_state.py -v`
Expected: FAIL with `AttributeError: module 'portfolio_app' has no attribute 'unflag_watchlisted'`

- [ ] **Step 3: Implement `unflag_watchlisted`**

In `portfolio_app.py`, find `flag_watchlisted` (it ends with a call to `save_watchlist_state(state)`)
and insert directly after it, before `evaluate_momentum_signal`:

```python
def unflag_watchlisted(ticker):
    state = load_watchlist_state()
    flagged = state.get("flagged", {})
    flagged.pop(ticker, None)
    state["flagged"] = flagged
    save_watchlist_state(state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_watchlist_state.py -v`
Expected: PASS (5 tests: 3 existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add tests/test_watchlist_state.py portfolio_app.py
git commit -m "feat: add unflag_watchlisted for manual watchlist dismissal"
```

---

### Task 2: `RE_ENTRY` signal branch

**Files:**
- Modify: `tests/test_momentum_signal.py` (append)
- Modify: `portfolio_app.py:` `evaluate_momentum_signal`'s BUY branch

**Interfaces:**
- Consumes: `is_watchlisted` (existing, Phase 1).
- Produces: `evaluate_momentum_signal` now returns `"RE_ENTRY"` (new value) in addition to its
  existing `"BUY"` / `"FULL_SELL"` / `"TRIM_TO_100"` / `"HOLD"` values.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_momentum_signal.py` (the `_technicals` helper already defined at the top
of this file from Phase 1 — reuse it, don't redefine it):

```python
def test_re_entry_when_watchlisted_ticker_hits_buy_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    portfolio_app.flag_watchlisted("NVDA")
    technicals = _technicals(macd="bullish", ma50="bullish")
    assert evaluate_momentum_signal("NVDA", 75, technicals) == "RE_ENTRY"


def test_buy_when_not_watchlisted_even_at_same_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bullish", ma50="bullish")
    assert evaluate_momentum_signal("NVDA", 75, technicals) == "BUY"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_momentum_signal.py -v`
Expected: `test_re_entry_when_watchlisted_ticker_hits_buy_threshold` FAILS (`assert 'BUY' == 'RE_ENTRY'`);
`test_buy_when_not_watchlisted_even_at_same_threshold` already passes (no behavior change for
that case yet) — that's expected, it's a regression guard for the next step.

- [ ] **Step 3: Implement the `RE_ENTRY` branch**

In `portfolio_app.py`, find `evaluate_momentum_signal` and replace:

```python
    if score >= 70 and bullish_count >= 2:
        return "BUY"
```

with:

```python
    if score >= 70 and bullish_count >= 2:
        return "RE_ENTRY" if is_watchlisted(ticker) else "BUY"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_momentum_signal.py -v`
Expected: PASS (all tests in this file)

- [ ] **Step 5: Commit**

```bash
git add tests/test_momentum_signal.py portfolio_app.py
git commit -m "feat: return RE_ENTRY instead of BUY for watchlisted tickers"
```

---

### Task 3: Wire `watchlisted_since` and `days_until_eligible` into `run_scoring()`

**Files:**
- Modify: `tests/test_run_scoring.py` (append)
- Modify: `portfolio_app.py:` `run_scoring`'s holdings loop

**Interfaces:**
- Consumes: `watchlisted_since` (existing, Phase 1), `MIN_DAYS_BEFORE_FULL_SELL` (existing
  constant, Phase 1).
- Produces: each position dict in `run_scoring()`'s output gains `"watchlisted_since"` (ISO
  string or `None`) and `"days_until_eligible"` (int or `None`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_run_scoring.py`:

```python
def test_run_scoring_includes_watchlisted_since_and_days_until_eligible(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (20.0, "Exit", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bearish", "ma50": "bearish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))
    # Note: evaluate_momentum_signal is NOT mocked here -- the real function must run so it
    # actually calls flag_watchlisted() on this low-score, bearish-confirmed ticker.

    holdings = [{"ticker": "CVNA", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)
    pos = result["positions"][0]

    assert pos["watchlisted_since"] is not None
    assert pos["days_until_eligible"] == 3  # just flagged, full window remains


def test_run_scoring_watchlist_fields_are_none_when_not_flagged(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (75.0, "High", "Technology", 100.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bullish", "ma50": "bullish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "NVDA", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)
    pos = result["positions"][0]

    assert pos["watchlisted_since"] is None
    assert pos["days_until_eligible"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_run_scoring.py -v`
Expected: FAIL with `KeyError: 'watchlisted_since'`

- [ ] **Step 3: Wire the new fields into the holdings loop**

In `portfolio_app.py`, find the line `momentum_signal = evaluate_momentum_signal(ticker, score, technicals)`
inside `run_scoring`'s loop and the `rows.append({...})` block that follows it. Replace:

```python
        score, tier, sector, live_price = score_asset(ticker)
        technicals      = get_technicals(ticker)
        momentum_signal = evaluate_momentum_signal(ticker, score, technicals)
        current_value   = shares * live_price
```

with:

```python
        score, tier, sector, live_price = score_asset(ticker)
        technicals      = get_technicals(ticker)
        momentum_signal = evaluate_momentum_signal(ticker, score, technicals)
        flagged_since   = watchlisted_since(ticker)
        days_until_eligible = None
        if flagged_since is not None:
            days_until_eligible = max(0, MIN_DAYS_BEFORE_FULL_SELL - (datetime.now() - flagged_since).days)
        current_value   = shares * live_price
```

Then add the two new keys to the `rows.append({...})` dict — replace:

```python
            "momentum_signal": momentum_signal,
        })
```

with:

```python
            "momentum_signal":     momentum_signal,
            "watchlisted_since":   flagged_since.isoformat() if flagged_since else None,
            "days_until_eligible": days_until_eligible,
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_run_scoring.py -v`
Expected: PASS (all tests in this file)

- [ ] **Step 5: Run the full suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1-3 plus everything from Phase 1)

- [ ] **Step 6: Commit**

```bash
git add tests/test_run_scoring.py portfolio_app.py
git commit -m "feat: expose watchlisted_since and days_until_eligible per position"
```

---

### Task 4: `/api/unwatch` route

**Files:**
- Create: `tests/test_unwatch_route.py`
- Modify: `portfolio_app.py` (insert after `/api/save-snapshot`, before `/api/price/<ticker>`)

**Interfaces:**
- Consumes: `unflag_watchlisted` (Task 1).
- Produces: `POST /api/unwatch` — request body `{"ticker": "<str>"}`. Response
  `{"ok": true}` with status 200, always (idempotent).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_unwatch_route.py`:

```python
import portfolio_app


def test_api_unwatch_clears_watchlist_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    portfolio_app.flag_watchlisted("NVDA")
    assert portfolio_app.is_watchlisted("NVDA") is True

    client = portfolio_app.app.test_client()
    resp = client.post("/api/unwatch", json={"ticker": "NVDA"})
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert portfolio_app.is_watchlisted("NVDA") is False


def test_api_unwatch_on_never_flagged_ticker_does_not_error(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    client = portfolio_app.app.test_client()
    resp = client.post("/api/unwatch", json={"ticker": "NVDA"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_unwatch_route.py -v`
Expected: FAIL with `404 NOT FOUND`

- [ ] **Step 3: Implement the route**

In `portfolio_app.py`, directly after the `/api/save-snapshot` route (`api_save_snapshot`) and
before `/api/price/<ticker>`, add:

```python
@app.route("/api/unwatch", methods=["POST"])
def api_unwatch():
    ticker = request.json.get("ticker", "")
    unflag_watchlisted(ticker)
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_unwatch_route.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_unwatch_route.py portfolio_app.py
git commit -m "feat: add /api/unwatch route"
```

---

### Task 5: Watchlist tab (frontend)

**Files:**
- Modify: `portfolio_app.py` (CSS, tab button, tab content, `showTab`, `renderResults`, two new
  JS helper functions, all within the `HTML_PAGE` string)

**Interfaces:**
- Consumes: `watchlisted_since`, `days_until_eligible` (Task 3), `momentum_signal` including the
  new `RE_ENTRY` value (Task 2), `/api/unwatch` (Task 4).
- No new Python interfaces — this is frontend HTML/CSS/JS.

- [ ] **Step 1: Add a CSS rule for `RE_ENTRY`**

Find the existing momentum-signal CSS rules (`.BUY`, `.TRIM`, `.HOLD`, `.FULL_SELL`,
`.TRIM_TO_100`) and add, directly after `.TRIM_TO_100`:

```css
  .RE_ENTRY { color: var(--green); text-shadow: 0 0 6px color-mix(in srgb, var(--green) 60%, transparent); font-weight: 900; }
```

- [ ] **Step 2: Add the Watchlist tab button**

Find the tab button row (`[ RANKINGS ]`, `[ BUYS ]`, `[ EXITS ]`, `[ SECTORS ]`, `[ TRIALS ]`)
and add a new button directly after the Trials button:

```html
        <button class="tab"        onclick="showTab('watchlist')">[ WATCHLIST ]</button>
```

- [ ] **Step 3: Add the Watchlist tab content**

Find the Trials tab's closing `</div>` (the one that closes `<div id="tab-trials" ...>`) and add
a new tab block directly after it, before the closing `</div>` of `#resultsArea`:

```html
      <!-- WATCHLIST -->
      <div id="tab-watchlist" class="hidden">
        <div class="table-wrap"><table>
          <thead><tr>
            <th>Ticker</th><th>Name</th><th>Score</th><th>Tier</th>
            <th>Flagged</th><th>Eligible In</th><th>Momentum</th><th></th>
          </tr></thead>
          <tbody id="watchlistBody"></tbody>
        </table></div>
      </div>
```

- [ ] **Step 4: Update `showTab` to include the new tab**

Find `function showTab(name) { ... }` and replace both array literals:

```js
function showTab(name) {
  ['rankings','buys','exits','sectors','trials'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('.tab').forEach((btn, i) => {
    btn.classList.toggle('active', ['rankings','buys','exits','sectors','trials'][i] === name);
  });
}
```

with:

```js
function showTab(name) {
  ['rankings','buys','exits','sectors','trials','watchlist'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('.tab').forEach((btn, i) => {
    btn.classList.toggle('active', ['rankings','buys','exits','sectors','trials','watchlist'][i] === name);
  });
}
```

- [ ] **Step 5: Add a `fmtDate` helper**

Find the existing format helpers (`fmtPrice`, `pnlClass`, etc.) and add, alongside them:

```js
function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleDateString() : '—';
}
```

- [ ] **Step 6: Render the Watchlist tab in `renderResults`**

Find the Trials rendering block in `renderResults` (it ends with the line setting
`document.getElementById('trialsBody').innerHTML = ...`) and add directly after it, before the
`document.getElementById('welcome').classList.add('hidden');` line:

```js
  // Watchlist
  const watchlist = all.filter(p => p.watchlisted_since).sort(byTierThenValue);
  document.getElementById('watchlistBody').innerHTML = watchlist.length ? watchlist.map(p => `<tr>
    <td class="ticker-cell">${p.ticker}</td>
    <td class="name-cell">${p.name||''}</td>
    <td>${scoreBar(p.score)}</td>
    <td><span class="tier tier-${p.tier}">${p.tier}</span></td>
    <td>${fmtDate(p.watchlisted_since)}</td>
    <td>${p.days_until_eligible === 0 ? 'Eligible' : p.days_until_eligible + 'd'}</td>
    <td><span class="action ${p.momentum_signal}">${p.momentum_signal}</span></td>
    <td><button class="btn-secondary" style="padding:3px 8px;font-size:9px" onclick="unwatchTicker('${p.ticker}')">Remove</button></td>
  </tr>`).join('') : '<tr><td colspan="8" class="empty">No positions on the watchlist</td></tr>';
```

- [ ] **Step 7: Add the `unwatchTicker` dismiss function**

Find `async function savePortfolio() { ... }` and add a new function directly after it:

```js
async function unwatchTicker(ticker) {
  try {
    await fetch('/api/unwatch', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ticker})
    });
    document.querySelectorAll('#watchlistBody tr').forEach(tr => {
      if (tr.querySelector('.ticker-cell')?.textContent.trim() === ticker) tr.remove();
    });
    toast(ticker + ' removed from watchlist');
  } catch (e) {
    toast('Failed to remove from watchlist: ' + e.message, true);
  }
}
```

- [ ] **Step 8: Run the full pytest suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (this is a frontend-only change; confirms no regressions)

- [ ] **Step 9: Manually verify in the browser**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 portfolio_app.py`

In the browser that opens:
1. Load your holdings and click Score.
2. Confirm a new "[ WATCHLIST ]" tab appears in the tab bar.
3. Click it — if nothing is currently watchlisted, confirm it shows "No positions on the
   watchlist" rather than an error or blank table.
4. If anything in your real portfolio is currently watchlisted (check by looking for
   `TRIM_TO_100`/`FULL_SELL` in the Momentum column on the Rankings tab, or by inspecting
   `watchlist_state.json` directly), confirm it appears on the Watchlist tab with a Flagged
   date and an Eligible-In countdown, and that clicking "Remove" makes the row disappear
   without an error.

Stop the server with Ctrl+C when done.

- [ ] **Step 10: Commit**

```bash
git add portfolio_app.py
git commit -m "feat: add Watchlist tab with dismiss action"
```

---

## Self-Review

**Spec coverage:** `unflag_watchlisted` (Task 1) ✓. `RE_ENTRY` branch (Task 2) ✓.
`watchlisted_since`/`days_until_eligible` exposed via `run_scoring` (Task 3) ✓. `/api/unwatch`
route (Task 4) ✓. Watchlist tab UI with dismiss button (Task 5) ✓. Error handling (idempotent
unflag, idempotent route, RE_ENTRY falling through correctly for non-watchlisted tickers) is
covered inline in Tasks 1, 2, and 4's tests. Out-of-scope items (trim trade-size calculation,
auto-clearing) are not implemented, matching the spec.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `momentum_signal` values (`BUY`/`RE_ENTRY`/`FULL_SELL`/`TRIM_TO_100`/`HOLD`)
match exactly between Task 2's implementation, Task 3's `run_scoring` test fixtures, and Task 5's
CSS/rendering. `watchlisted_since`/`days_until_eligible` field names and null-handling match
exactly between Task 3's implementation and Task 5's frontend consumption (`p.watchlisted_since`,
`p.days_until_eligible`).
