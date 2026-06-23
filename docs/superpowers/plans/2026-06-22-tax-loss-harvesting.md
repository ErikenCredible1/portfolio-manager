# Tax-Loss Harvesting (Phase 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recommend a set of currently-losing positions to sell in December up to the $3,000/year
limit (adjusted for losses already realized this year), and warn about wash-sale risk if a
recently-harvested ticker gets re-added to holdings within 31 days.

**Architecture:** A new `realized_sales.json` state file (mirroring the existing
`watchlist_state.json` pattern) tracks manually-logged sales — both one-click "Mark as
Harvested" entries and a general-purpose log form for any sale, any time of year. Two new
per-position fields (`tax_harvest_candidate`, `wash_sale_clear_date`) and two new top-level
summary fields ride the existing `run_scoring()` → `/api/score` response, same as every prior
phase — no separate GET endpoint.

**Tech Stack:** Flask, pandas (existing — no new dependencies).

## Global Constraints

- New state file: `realized_sales.json`, format `{"sales": [{"ticker", "amount", "date", "pos_type"}]}`.
- `TAX_LOSS_ANNUAL_LIMIT = 3000`, `WASH_SALE_DAYS = 31` — hardcoded module constants.
- `is_harvest_month()` returns `datetime.now().month == 12` — kept as its own function
  specifically so tests can monkeypatch it directly instead of mocking `datetime`.
- `realized_losses_this_year()` sums negative-`amount` entries whose `date` falls in the
  current calendar year; returns `0` (not negative-zero or `None`) when there are none.
- `wash_sale_clear_date_for(ticker)` uses the *most recent* log entry for that ticker; returns
  `None` if there's no entry or the most recent one is 31+ days old.
- `select_tax_harvest_candidates(positions, remaining_target)` is a pure function (no I/O):
  takes an iterable of `(ticker, pnl)` pairs, returns the set of tickers selected by greedily
  filling from the largest loss down, skipping (not stopping at) any loss that would push the
  running total over `remaining_target`.
- `tax_harvest_candidate` (bool) and `wash_sale_clear_date` (ISO string or `None`) are fully
  independent of `action`/`momentum_signal`/`over_position_cap` — none of these fields read or
  write each other.
- Tests run from the project root with: `python3 -m pytest tests/ -v`

---

## File Structure

- **Modify:** `portfolio_app.py` — the `datetime` import (add `timedelta`), the realized-sales
  state layer, `select_tax_harvest_candidates`, `is_harvest_month`, the `run_scoring()` wiring,
  the `/api/log-sale` route, and the frontend HTML/CSS/JS for the new Tax Harvest tab.
- **Create:** `tests/test_realized_sales.py`
- **Create:** `tests/test_tax_harvest_selection.py`
- **Create:** `tests/test_log_sale_route.py`

---

### Task 1: Realized-sales state layer

**Files:**
- Create: `tests/test_realized_sales.py`
- Modify: `portfolio_app.py` (import, constants, new functions after `unflag_watchlisted`)

**Interfaces:**
- Produces: `load_realized_sales() -> dict`, `save_realized_sales(state: dict) -> None`,
  `log_realized_sale(ticker: str, amount: float, pos_type: str) -> None`,
  `realized_losses_this_year() -> float`, `wash_sale_clear_date_for(ticker: str) -> datetime | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_realized_sales.py`:

```python
from datetime import datetime, timedelta

import portfolio_app
from portfolio_app import (
    load_realized_sales,
    log_realized_sale,
    realized_losses_this_year,
    wash_sale_clear_date_for,
)


def test_log_realized_sale_persists_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    log_realized_sale("CVNA", -450.0, "main")
    state = load_realized_sales()
    assert len(state["sales"]) == 1
    assert state["sales"][0]["ticker"] == "CVNA"
    assert state["sales"][0]["amount"] == -450.0
    assert state["sales"][0]["pos_type"] == "main"


def test_realized_losses_this_year_sums_losses_only(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    log_realized_sale("CVNA", -450.0, "main")
    log_realized_sale("NVDA", 800.0, "main")   # a gain -- must not count
    log_realized_sale("SOFI", -200.0, "trial")
    assert realized_losses_this_year() == -650.0


def test_realized_losses_this_year_excludes_prior_year(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    state = {"sales": [
        {"ticker": "OLD", "amount": -999.0, "date": "2020-01-01T00:00:00", "pos_type": "main"},
    ]}
    portfolio_app.save_realized_sales(state)
    log_realized_sale("CVNA", -100.0, "main")
    assert realized_losses_this_year() == -100.0


def test_realized_losses_this_year_is_zero_when_no_sales(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    assert realized_losses_this_year() == 0


def test_wash_sale_clear_date_for_within_window(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    log_realized_sale("CVNA", -450.0, "main")
    clear_date = wash_sale_clear_date_for("CVNA")
    assert clear_date is not None
    expected = datetime.now() + timedelta(days=portfolio_app.WASH_SALE_DAYS)
    assert abs((clear_date - expected).total_seconds()) < 5


def test_wash_sale_clear_date_for_outside_window_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    old_date = (datetime.now() - timedelta(days=40)).isoformat()
    state = {"sales": [{"ticker": "CVNA", "amount": -450.0, "date": old_date, "pos_type": "main"}]}
    portfolio_app.save_realized_sales(state)
    assert wash_sale_clear_date_for("CVNA") is None


def test_wash_sale_clear_date_for_no_history_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    assert wash_sale_clear_date_for("NVDA") is None


def test_wash_sale_clear_date_for_uses_most_recent_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    old_date = (datetime.now() - timedelta(days=40)).isoformat()
    state = {"sales": [{"ticker": "CVNA", "amount": -100.0, "date": old_date, "pos_type": "main"}]}
    portfolio_app.save_realized_sales(state)
    log_realized_sale("CVNA", -50.0, "main")  # more recent than the 40-day-old entry
    assert wash_sale_clear_date_for("CVNA") is not None  # governed by the recent entry
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_realized_sales.py -v`
Expected: FAIL with `AttributeError: module 'portfolio_app' has no attribute 'load_realized_sales'`

- [ ] **Step 3: Implement the state layer**

In `portfolio_app.py`, find the import line `from datetime import datetime` and replace it with:

```python
from datetime import datetime, timedelta
```

Find `WATCHLIST_FILE = "watchlist_state.json"` and add directly after it:

```python
REALIZED_SALES_FILE   = "realized_sales.json"
TAX_LOSS_ANNUAL_LIMIT  = 3000
WASH_SALE_DAYS         = 31
```

Find `unflag_watchlisted` (it ends with a call to `save_watchlist_state(state)`) and insert
directly after it, before `evaluate_momentum_signal`:

```python
def load_realized_sales():
    if os.path.exists(REALIZED_SALES_FILE):
        with open(REALIZED_SALES_FILE) as f:
            return json.load(f)
    return {"sales": []}


def save_realized_sales(state):
    with open(REALIZED_SALES_FILE, "w") as f:
        json.dump(state, f, indent=2)


def log_realized_sale(ticker, amount, pos_type):
    state = load_realized_sales()
    sales = state.get("sales", [])
    sales.append({
        "ticker":   ticker,
        "amount":   amount,
        "date":     datetime.now().isoformat(),
        "pos_type": pos_type,
    })
    state["sales"] = sales
    save_realized_sales(state)


def realized_losses_this_year():
    state     = load_realized_sales()
    this_year = datetime.now().year
    total     = 0.0
    for sale in state.get("sales", []):
        sale_date = datetime.fromisoformat(sale["date"])
        if sale_date.year == this_year and sale["amount"] < 0:
            total += sale["amount"]
    return total


def wash_sale_clear_date_for(ticker):
    state    = load_realized_sales()
    matching = [s for s in state.get("sales", []) if s["ticker"] == ticker]
    if not matching:
        return None
    latest    = max(matching, key=lambda s: s["date"])
    sale_date = datetime.fromisoformat(latest["date"])
    if (datetime.now() - sale_date).days >= WASH_SALE_DAYS:
        return None
    return sale_date + timedelta(days=WASH_SALE_DAYS)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_realized_sales.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Run the full suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests, including everything from Phases 1-3a)

- [ ] **Step 6: Commit**

```bash
git add tests/test_realized_sales.py portfolio_app.py
git commit -m "feat: add realized-sales state layer for tax-loss tracking"
```

---

### Task 2: `select_tax_harvest_candidates` (pure greedy selection)

**Files:**
- Create: `tests/test_tax_harvest_selection.py`
- Modify: `portfolio_app.py` (insert after `wash_sale_clear_date_for`, before `evaluate_momentum_signal`)

**Interfaces:**
- Consumes: nothing new — a pure function.
- Produces: `select_tax_harvest_candidates(positions: list[tuple[str, float]], remaining_target: float) -> set[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tax_harvest_selection.py`:

```python
from portfolio_app import select_tax_harvest_candidates


def test_selects_all_when_everything_fits():
    positions = [("A", -1000.0), ("B", -1500.0), ("C", -200.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == {"A", "B", "C"}  # total 2700, all fit


def test_skips_a_loss_that_would_overshoot_but_keeps_checking_smaller_ones():
    # A (2000, largest) is taken first. B (1800) would push the total to 3800 and is
    # skipped. C (900) is checked next and still fits (2000 + 900 = 2900) -- proving the
    # algorithm keeps looking past the first miss instead of stopping.
    positions = [("A", -2000.0), ("B", -1800.0), ("C", -900.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == {"A", "C"}


def test_ignores_gains():
    positions = [("A", -500.0), ("B", 900.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == {"A"}


def test_returns_empty_set_when_target_is_zero():
    positions = [("A", -500.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=0)
    assert selected == set()


def test_returns_empty_set_with_no_losers():
    positions = [("A", 500.0), ("B", 200.0)]
    selected = select_tax_harvest_candidates(positions, remaining_target=3000)
    assert selected == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_tax_harvest_selection.py -v`
Expected: FAIL with `ImportError: cannot import name 'select_tax_harvest_candidates'`

- [ ] **Step 3: Implement the selection function**

In `portfolio_app.py`, directly after `wash_sale_clear_date_for` (added in Task 1) and before
`evaluate_momentum_signal`, insert:

```python
def select_tax_harvest_candidates(positions, remaining_target):
    """positions: iterable of (ticker, pnl) pairs. Greedily selects losing positions,
    largest loss first, accumulating up to but not exceeding remaining_target. A loss that
    would overshoot is skipped (not a stopping point) so smaller losses further down the
    list still get a chance to fit. Returns the set of selected tickers."""
    losers = sorted((p for p in positions if p[1] < 0), key=lambda p: p[1])
    selected = set()
    running_total = 0.0
    for ticker, pnl in losers:
        loss = abs(pnl)
        if running_total + loss <= remaining_target:
            selected.add(ticker)
            running_total += loss
    return selected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_tax_harvest_selection.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_tax_harvest_selection.py portfolio_app.py
git commit -m "feat: add select_tax_harvest_candidates greedy fill"
```

---

### Task 3: Wire `tax_harvest_candidate` and `wash_sale_clear_date` into `run_scoring()`

**Files:**
- Create: `tests/test_tax_harvest_run_scoring.py`
- Modify: `portfolio_app.py` (`is_harvest_month`, the holdings loop, the post-DataFrame
  computation block, the final return dict)

**Interfaces:**
- Consumes: `wash_sale_clear_date_for` (Task 1), `realized_losses_this_year` (Task 1),
  `select_tax_harvest_candidates` (Task 2).
- Produces: `is_harvest_month() -> bool`. Every position gains `"tax_harvest_candidate": bool`
  and `"wash_sale_clear_date": str | None`. The top-level `run_scoring()` result dict gains
  `"tax_harvest_realized_this_year": float | None` and `"tax_harvest_target_remaining": float | None`
  (both `None` outside December).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tax_harvest_run_scoring.py`:

```python
import portfolio_app


def _technicals_neutral(ticker):
    return {"macd": "neutral", "ma50": "neutral", "rsi_failure_swing": "neutral"}


def test_run_scoring_flags_tax_harvest_candidates_in_december(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: True)

    prices = {"LOSER": (20.0, "Exit", "Technology", 50.0), "WINNER": (75.0, "High", "Technology", 200.0)}
    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: prices[ticker])
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [
        {"ticker": "LOSER", "shares": "10", "invested": "1000", "type": "main"},   # value=500, pnl=-500
        {"ticker": "WINNER", "shares": "5", "invested": "500", "type": "main"},    # value=1000, pnl=+500
    ]
    result = portfolio_app.run_scoring(holdings)
    by_ticker = {p["ticker"]: p for p in result["positions"]}

    assert by_ticker["LOSER"]["tax_harvest_candidate"] is True
    assert by_ticker["WINNER"]["tax_harvest_candidate"] is False
    assert result["tax_harvest_target_remaining"] == 3000
    assert result["tax_harvest_realized_this_year"] == 0


def test_run_scoring_never_flags_tax_harvest_candidates_outside_december(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: False)

    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: (20.0, "Exit", "Technology", 50.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "LOSER", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)

    assert result["positions"][0]["tax_harvest_candidate"] is False
    assert result["tax_harvest_target_remaining"] is None
    assert result["tax_harvest_realized_this_year"] is None


def test_run_scoring_target_remaining_reduced_by_prior_realized_losses(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: True)
    portfolio_app.log_realized_sale("OLDSALE", -1200.0, "main")

    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: (20.0, "Exit", "Technology", 50.0))
    monkeypatch.setattr(portfolio_app, "get_technicals", _technicals_neutral)
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "LOSER", "shares": "10", "invested": "1000", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)

    assert result["tax_harvest_realized_this_year"] == 1200
    assert result["tax_harvest_target_remaining"] == 1800  # 3000 - 1200


def test_run_scoring_includes_wash_sale_clear_date_for_recently_logged_ticker(monkeypatch, tmp_path):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    monkeypatch.setattr(portfolio_app, "is_harvest_month", lambda: False)
    portfolio_app.log_realized_sale("NVDA", -300.0, "main")

    monkeypatch.setattr(portfolio_app, "score_asset", lambda ticker: (75.0, "High", "Technology", 200.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bullish", "ma50": "bullish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "NVDA", "shares": "5", "invested": "500", "type": "main"}]
    result = portfolio_app.run_scoring(holdings)
    pos = result["positions"][0]

    assert pos["wash_sale_clear_date"] is not None
    assert pos["momentum_signal"] in ("BUY", "RE_ENTRY")  # unaffected by wash-sale status
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_tax_harvest_run_scoring.py -v`
Expected: FAIL with `AttributeError: module 'portfolio_app' has no attribute 'is_harvest_month'`

- [ ] **Step 3: Implement `is_harvest_month` and wire the new fields into `run_scoring`**

In `portfolio_app.py`, directly after `select_tax_harvest_candidates` (added in Task 2) and
before `evaluate_momentum_signal`, insert:

```python
def is_harvest_month():
    return datetime.now().month == 12
```

Inside `run_scoring`'s holdings loop, find:

```python
        flagged_since   = watchlisted_since(ticker)
        days_until_eligible = None
        if flagged_since is not None:
            days_until_eligible = max(0, MIN_DAYS_BEFORE_FULL_SELL - (datetime.now() - flagged_since).days)
        current_value   = shares * live_price
```

and replace it with:

```python
        flagged_since   = watchlisted_since(ticker)
        days_until_eligible = None
        if flagged_since is not None:
            days_until_eligible = max(0, MIN_DAYS_BEFORE_FULL_SELL - (datetime.now() - flagged_since).days)
        wash_clear_date = wash_sale_clear_date_for(ticker)
        current_value   = shares * live_price
```

Then find the `rows.append({...})` block's tail:

```python
            "momentum_signal":     momentum_signal,
            "watchlisted_since":   flagged_since.isoformat() if flagged_since else None,
            "days_until_eligible": days_until_eligible,
        })
```

and replace it with:

```python
            "momentum_signal":      momentum_signal,
            "watchlisted_since":    flagged_since.isoformat() if flagged_since else None,
            "days_until_eligible":  days_until_eligible,
            "wash_sale_clear_date": wash_clear_date.isoformat() if wash_clear_date else None,
        })
```

Find the `over_position_cap` block:

```python
    main_mask   = df["pos_type"] != "trial"
    main_ranked = df[main_mask].sort_values("score", ascending=False)
    excess      = set(main_ranked.iloc[MAX_MAIN_POSITIONS:]["ticker"]) if len(main_ranked) > MAX_MAIN_POSITIONS else set()
    df["over_position_cap"] = df["ticker"].isin(excess)

    df = df.sort_values("score", ascending=False).reset_index(drop=True)
```

and replace it with:

```python
    main_mask   = df["pos_type"] != "trial"
    main_ranked = df[main_mask].sort_values("score", ascending=False)
    excess      = set(main_ranked.iloc[MAX_MAIN_POSITIONS:]["ticker"]) if len(main_ranked) > MAX_MAIN_POSITIONS else set()
    df["over_position_cap"] = df["ticker"].isin(excess)

    if is_harvest_month():
        realized_this_year = abs(realized_losses_this_year())
        remaining_target    = max(0, TAX_LOSS_ANNUAL_LIMIT - realized_this_year)
        tax_candidates       = select_tax_harvest_candidates(list(zip(df["ticker"], df["pnl"])), remaining_target)
    else:
        realized_this_year = None
        remaining_target    = None
        tax_candidates       = set()
    df["tax_harvest_candidate"] = df["ticker"].isin(tax_candidates)

    df = df.sort_values("score", ascending=False).reset_index(drop=True)
```

Finally, find the function's return statement:

```python
    return {
        "total_value":    round(float(total), 2),
        "total_invested": round(total_invested, 2),
        "total_pnl":      round(float(total) - total_invested, 2),
        "positions":      positions,
        "sectors":        sectors,
        "regime":         regime,
        "semi_cap":       semi_cap,
        "position_count": len(positions),
    }
```

and replace it with:

```python
    return {
        "total_value":    round(float(total), 2),
        "total_invested": round(total_invested, 2),
        "total_pnl":      round(float(total) - total_invested, 2),
        "positions":      positions,
        "sectors":        sectors,
        "regime":         regime,
        "semi_cap":       semi_cap,
        "position_count": len(positions),
        "tax_harvest_realized_this_year": round(realized_this_year, 2) if realized_this_year is not None else None,
        "tax_harvest_target_remaining":   round(remaining_target, 2) if remaining_target is not None else None,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_tax_harvest_run_scoring.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add tests/test_tax_harvest_run_scoring.py portfolio_app.py
git commit -m "feat: wire tax_harvest_candidate and wash_sale_clear_date into run_scoring"
```

---

### Task 4: `/api/log-sale` route

**Files:**
- Create: `tests/test_log_sale_route.py`
- Modify: `portfolio_app.py` (insert after `/api/unwatch`, before `/api/price/<ticker>`)

**Interfaces:**
- Consumes: `log_realized_sale` (Task 1).
- Produces: `POST /api/log-sale` — request body `{"ticker": "<str>", "amount": <number>, "pos_type": "main"|"trial"}`.
  Response `{"ok": true}` with status 200. `ticker` is normalized to uppercase; `pos_type`
  defaults to `"main"` if omitted.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_log_sale_route.py`:

```python
import portfolio_app


def test_api_log_sale_persists_entry_with_uppercased_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    client = portfolio_app.app.test_client()
    resp = client.post("/api/log-sale", json={"ticker": "cvna", "amount": -450.0, "pos_type": "main"})
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    state = portfolio_app.load_realized_sales()
    assert state["sales"][0]["ticker"] == "CVNA"
    assert state["sales"][0]["amount"] == -450.0


def test_api_log_sale_defaults_pos_type_to_main(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "REALIZED_SALES_FILE", str(tmp_path / "realized_sales.json"))
    client = portfolio_app.app.test_client()
    resp = client.post("/api/log-sale", json={"ticker": "NVDA", "amount": -100.0})

    assert resp.status_code == 200
    state = portfolio_app.load_realized_sales()
    assert state["sales"][0]["pos_type"] == "main"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_log_sale_route.py -v`
Expected: FAIL with `404 NOT FOUND`

- [ ] **Step 3: Implement the route**

In `portfolio_app.py`, directly after the `/api/unwatch` route (`api_unwatch`) and before
`/api/price/<ticker>`, add:

```python
@app.route("/api/log-sale", methods=["POST"])
def api_log_sale():
    data     = request.json
    ticker   = data.get("ticker", "").strip().upper()
    amount   = float(data.get("amount", 0))
    pos_type = data.get("pos_type", "main")
    log_realized_sale(ticker, amount, pos_type)
    return jsonify({"ok": True})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_log_sale_route.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add tests/test_log_sale_route.py portfolio_app.py
git commit -m "feat: add /api/log-sale route"
```

---

### Task 5: Tax Harvest tab (frontend)

**Files:**
- Modify: `portfolio_app.py` (tab button, tab content, `showTab`, `renderResults`, two new JS
  functions, all within the `HTML_PAGE` string)

**Interfaces:**
- Consumes: `tax_harvest_candidate`, `wash_sale_clear_date` (Task 3), `tax_harvest_target_remaining`,
  `tax_harvest_realized_this_year` (Task 3, top-level response fields), `/api/log-sale` (Task 4).
- No new Python interfaces — frontend HTML/CSS/JS only.

- [ ] **Step 1: Add the Tax Harvest tab button**

Find the Watchlist tab button (`onclick="showTab('watchlist')"`) and add directly after it:

```html
        <button class="tab"        onclick="showTab('taxharvest')">[ TAX HARVEST ]</button>
```

- [ ] **Step 2: Add the Tax Harvest tab content**

Find the Watchlist tab's closing `</div>` (the one closing `<div id="tab-watchlist" ...>`,
immediately followed by `</div>` closing `#resultsArea`) and insert a new tab block directly
after it, before that `#resultsArea`-closing `</div>`:

```html
      <!-- TAX HARVEST -->
      <div id="tab-taxharvest" class="hidden">
        <div id="taxHarvestSummary" style="margin-bottom:14px;font-size:11px;color:var(--muted)"></div>

        <div class="table-wrap"><table>
          <thead><tr>
            <th>Ticker</th><th>Name</th><th>Tier</th>
            <th class="r">P&amp;L $</th><th class="r">Cumulative</th><th></th>
          </tr></thead>
          <tbody id="taxHarvestBody"></tbody>
        </table></div>

        <div style="margin-top:18px;font-size:10px;color:var(--dim);max-width:520px">
          Wash sale rule: if you rebuy the same ticker within 30 days before or after a tax-loss sale, the IRS disallows that loss for this year's taxes. Wait until the clear date below before repurchasing.
        </div>
        <div class="table-wrap" style="margin-top:8px"><table>
          <thead><tr><th>Ticker</th><th>Clears</th></tr></thead>
          <tbody id="washSaleBody"></tbody>
        </table></div>

        <div style="margin-top:18px;border-top:1px solid var(--border);padding-top:14px">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--muted);margin-bottom:8px">Log a Realized Sale</div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            <input id="logSaleTicker" placeholder="Ticker" style="background:var(--surface2);border:1px solid var(--border2);color:var(--text);font-family:var(--font);font-size:11px;padding:6px 8px;border-radius:4px;width:80px;text-transform:uppercase">
            <input id="logSaleAmount" placeholder="Amount ($, negative = loss)" type="number" style="background:var(--surface2);border:1px solid var(--border2);color:var(--text);font-family:var(--font);font-size:11px;padding:6px 8px;border-radius:4px;width:200px">
            <select id="logSalePosType" style="background:var(--surface2);border:1px solid var(--border2);color:var(--text);font-family:var(--font);font-size:11px;padding:6px 8px;border-radius:4px">
              <option value="main">Main</option>
              <option value="trial">Trial</option>
            </select>
            <button class="btn btn-secondary" onclick="logSale()">Log Sale</button>
          </div>
        </div>
      </div>
```

- [ ] **Step 3: Update `showTab` to include the new tab**

Find `function showTab(name) { ... }` and replace both array literals:

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

with:

```js
function showTab(name) {
  ['rankings','buys','exits','sectors','trials','watchlist','taxharvest'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('hidden', t !== name);
  });
  document.querySelectorAll('.tab').forEach((btn, i) => {
    btn.classList.toggle('active', ['rankings','buys','exits','sectors','trials','watchlist','taxharvest'][i] === name);
  });
}
```

- [ ] **Step 4: Render the Tax Harvest tab in `renderResults`**

Find the Watchlist rendering block in `renderResults` (it ends with the line setting
`document.getElementById('watchlistBody').innerHTML = ...`) and add directly after it, before
the `document.getElementById('welcome').classList.add('hidden');` line:

```js
  // Tax Harvest
  const taxCandidates = all.filter(p => p.tax_harvest_candidate);
  const summaryEl = document.getElementById('taxHarvestSummary');
  if (data.tax_harvest_target_remaining != null) {
    summaryEl.innerHTML = `Target: ${fmt$(data.tax_harvest_target_remaining)} remaining of $3,000 &mdash; ${fmt$(data.tax_harvest_realized_this_year)} already realized this year`;
  } else {
    summaryEl.innerHTML = 'No tax-loss harvesting candidates this month &mdash; recommendations appear in December.';
  }

  let taxCumulative = 0;
  document.getElementById('taxHarvestBody').innerHTML = taxCandidates.length ? taxCandidates.map(p => {
    taxCumulative += Math.abs(p.pnl);
    return `<tr>
      <td class="ticker-cell">${p.ticker}</td>
      <td class="name-cell">${p.name||''}</td>
      <td><span class="tier tier-${p.tier}">${p.tier}</span></td>
      <td class="r pnl-neg">${fmt$(p.pnl)}</td>
      <td class="r">${fmt$(taxCumulative)}</td>
      <td><button class="btn btn-secondary" style="padding:3px 8px;font-size:9px" onclick="markHarvested('${p.ticker}', ${p.pnl}, '${p.pos_type}')">Mark as Harvested</button></td>
    </tr>`;
  }).join('') : '<tr><td colspan="6" class="empty">No tax-loss harvesting candidates this month</td></tr>';

  const washRestricted = all.filter(p => p.wash_sale_clear_date);
  document.getElementById('washSaleBody').innerHTML = washRestricted.length ? washRestricted.map(p => `<tr>
    <td class="ticker-cell">${p.ticker}</td>
    <td>${fmtDate(p.wash_sale_clear_date)}</td>
  </tr>`).join('') : '<tr><td colspan="2" class="empty">No active wash-sale restrictions</td></tr>';
```

- [ ] **Step 5: Add the `markHarvested` and `logSale` functions**

Find `async function unwatchTicker(ticker) { ... }` and add directly after it:

```js
async function markHarvested(ticker, amount, posType) {
  try {
    await fetch('/api/log-sale', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ticker, amount, pos_type: posType})
    });
    document.querySelectorAll('#taxHarvestBody tr').forEach(tr => {
      if (tr.querySelector('.ticker-cell')?.textContent.trim() === ticker) tr.remove();
    });
    toast(ticker + ' logged as harvested');
  } catch (e) {
    toast('Failed to log sale: ' + e.message, true);
  }
}

async function logSale() {
  const ticker  = document.getElementById('logSaleTicker').value.trim().toUpperCase();
  const amount  = parseFloat(document.getElementById('logSaleAmount').value);
  const posType = document.getElementById('logSalePosType').value;
  if (!ticker || isNaN(amount)) { toast('Enter a ticker and a valid amount', true); return; }

  try {
    await fetch('/api/log-sale', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ticker, amount, pos_type: posType})
    });
    document.getElementById('logSaleTicker').value = '';
    document.getElementById('logSaleAmount').value = '';
    toast(ticker + ' sale logged');
  } catch (e) {
    toast('Failed to log sale: ' + e.message, true);
  }
}
```

- [ ] **Step 6: Run the full pytest suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (this is a frontend-only change; confirms no regressions)

- [ ] **Step 7: Manually verify in the browser**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 portfolio_app.py`

In the browser that opens:
1. Load your holdings and click Score.
2. Confirm a new "[ TAX HARVEST ]" tab appears, after Watchlist.
3. Click it. Outside December, confirm it shows "No tax-loss harvesting candidates this month"
   plus the wash-sale explainer, an (likely empty) wash-sale restrictions table, and the "Log a
   Realized Sale" form.
4. Try the log form: enter a fake ticker and a negative amount, click "Log Sale," confirm a
   success toast and that `realized_sales.json` now contains that entry on disk.
5. If you want to see the December recommendation table render, you can temporarily change
   `is_harvest_month` to `return True` in the code, reload, confirm the candidates table and
   summary line populate correctly, then change it back before committing anything further.

Stop the server with Ctrl+C when done.

- [ ] **Step 8: Commit**

```bash
git add portfolio_app.py
git commit -m "feat: add Tax Harvest tab with recommendations, wash-sale list, and log form"
```

---

## Self-Review

**Spec coverage:** Realized-sales state layer (Task 1) ✓. Greedy selection algorithm with
skip-not-stop behavior (Task 2) ✓. December gating via `is_harvest_month`, target reduction by
prior realized losses, wash-sale field independent of other signals (Task 3) ✓. Manual log
route (Task 4) ✓. Tax Harvest tab — recommendations, wash-sale list with explainer, log form
(Task 5) ✓. Error handling (no losers, target already at 0, no log history, year rollover,
most-recent-entry-wins) is covered inline in Tasks 1 and 3's tests. Out-of-scope items
(auto-detecting sales, exact subset-sum optimization, full gains/losses netting) are not
implemented, matching the spec.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `realized_losses_this_year()` returns a `float` (negative or `0`) used
consistently in Task 3's `abs(...)` call. `select_tax_harvest_candidates`'s `(ticker, pnl)`
tuple shape matches exactly how Task 3 constructs it (`zip(df["ticker"], df["pnl"])`).
`tax_harvest_candidate`/`wash_sale_clear_date` field names and `None`-handling match exactly
between Task 3's implementation and Task 5's frontend consumption (`p.tax_harvest_candidate`,
`p.wash_sale_clear_date`, `data.tax_harvest_target_remaining`, `data.tax_harvest_realized_this_year`).
