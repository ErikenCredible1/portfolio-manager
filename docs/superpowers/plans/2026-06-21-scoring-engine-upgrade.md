# Scoring Engine Upgrade (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stale 1m/6m/12m momentum weighting in `portfolio_app.py` with a 1w/1m/3m/6m scheme, add MACD/50-MA/RSI-failure-swing confirmation, and surface a clear `momentum_signal` (BUY/FULL_SELL/TRIM_TO_100/HOLD) per position, distinct from the existing weight-based `action` (BUY/TRIM/HOLD).

**Architecture:** Pure-logic functions (momentum math, indicator math, signal decision) are extracted and unit-tested in isolation with synthetic data — no network calls in tests. `score_asset()` keeps its existing signature; new functions (`get_technicals`, `evaluate_momentum_signal`) are called separately from `run_scoring()`, which adds new fields to its JSON output. A small `watchlist_state.json` file tracks repeat-offender state, decoupled from the user's manually-saved holdings data.

**Tech Stack:** Python 3.9, Flask, pandas, numpy, yfinance (existing). pytest (new, dev-only dependency).

## Global Constants

- Momentum weights/periods/clips: 1w (5 days, 10%, clip ±5%), 1m (21 days, 35%, clip ±10%), 3m (63 days, 40%, clip -15%/+18%), 6m (126 days, 15%, clip -15%/+20%). Scale factor stays `* (35/10)`.
- RSI period: 14. Failure-swing lookback window: 20 trading days. RSI overbought/oversold thresholds: 70/30.
- MACD: 12/26/9 EMA (standard). Minimum history for a non-neutral MACD reading: 35 days.
- 50-day MA: minimum history for a non-neutral reading: 50 days.
- `momentum_signal` thresholds: BUY needs score ≥ 70 and ≥2 of 3 technicals bullish. SELL path triggers at score < 30 and ≥2 of 3 technicals bearish (first trigger per ticker → `TRIM_TO_100`, repeat → `FULL_SELL`).
- Watchlist state file: `watchlist_state.json` (project root, gitignored, separate from `portfolio_data.json`).
- Rebalancing `action` field values are `BUY` / `TRIM` / `HOLD` (renamed from `BUY`/`SELL`/`HOLD` — logic unchanged).
- Tests run from the project root with: `python3 -m pytest tests/ -v`

---

## File Structure

- **Modify:** `portfolio_app.py` — all production code changes (momentum scoring, technical indicators, signal logic, watchlist persistence, `run_scoring()` wiring, frontend HTML/CSS/JS).
- **Create:** `tests/conftest.py` — makes `portfolio_app` importable from `tests/`.
- **Create:** `tests/test_action.py`
- **Create:** `tests/test_momentum_score.py`
- **Create:** `tests/test_rsi_failure_swing.py`
- **Create:** `tests/test_technicals.py`
- **Create:** `tests/test_watchlist_state.py`
- **Create:** `tests/test_momentum_signal.py`
- **Create:** `tests/test_run_scoring.py`

---

### Task 1: Test scaffolding + rename rebalancing SELL → TRIM

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_action.py`
- Modify: `portfolio_app.py:321-323` (insert `compute_action`), `portfolio_app.py:367-369` (use it), `portfolio_app.py:560` (CSS rename)

**Interfaces:**
- Produces: `compute_action(trade_value: float) -> str`, returns `"BUY"` / `"TRIM"` / `"HOLD"`.

- [ ] **Step 1: Install pytest and create the test scaffolding**

```bash
pip3 install pytest
```

Create `tests/conftest.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_action.py`:

```python
from portfolio_app import compute_action


def test_compute_action_buy_above_threshold():
    assert compute_action(51) == "BUY"


def test_compute_action_trim_below_negative_threshold():
    assert compute_action(-51) == "TRIM"


def test_compute_action_hold_within_threshold():
    assert compute_action(0) == "HOLD"
    assert compute_action(50) == "HOLD"
    assert compute_action(-50) == "HOLD"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_action.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_action'`

- [ ] **Step 4: Implement `compute_action` and wire it in**

In `portfolio_app.py`, between line 321 (`    return df`) and line 324 (`def run_scoring(holdings):`), insert:

```python
def compute_action(trade_value):
    if trade_value > 50:
        return "BUY"
    if trade_value < -50:
        return "TRIM"
    return "HOLD"
```

Replace the existing action computation at `portfolio_app.py:367-369`:

```python
    df["action"] = df["trade_value"].apply(
        lambda x: "BUY" if x > 50 else ("SELL" if x < -50 else "HOLD")
    )
```

with:

```python
    df["action"] = df["trade_value"].apply(compute_action)
```

In the CSS block, replace `portfolio_app.py:560`:

```css
  .SELL { color: var(--red); }
```

with:

```css
  .TRIM { color: var(--red); }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_action.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_action.py portfolio_app.py
git commit -m "refactor: extract compute_action, rename rebalancing SELL to TRIM"
```

---

### Task 2: New momentum weighting (1w/1m/3m/6m)

**Files:**
- Create: `tests/test_momentum_score.py`
- Modify: `portfolio_app.py:218-239` (insert `compute_momentum_score`, rewrite the momentum block in `score_asset`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `compute_momentum_score(price: pd.Series) -> float`. Used by `score_asset()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_momentum_score.py`:

```python
import pandas as pd
import pytest

from portfolio_app import compute_momentum_score


def _make_price_series(length, last, w1, m1, m3, m6):
    """Builds a price series where only the indices the function actually reads
    (-1, -6, -21, -63, -126) carry meaningful values; everything else is filler."""
    prices = pd.Series([100.0] * length)
    prices.iloc[-1]   = last
    prices.iloc[-6]   = w1
    prices.iloc[-21]  = m1
    prices.iloc[-63]  = m3
    prices.iloc[-126] = m6
    return prices


def test_compute_momentum_score_clips_only_the_1w_leg():
    # All four legs have a raw 10% return; only 1w's +5% cap should clip.
    price = _make_price_series(130, last=110, w1=100, m1=100, m3=100, m6=100)
    expected = (5 * 0.10 + 10 * 0.35 + 10 * 0.40 + 10 * 0.15) * (35 / 10)
    assert compute_momentum_score(price) == pytest.approx(expected)


def test_compute_momentum_score_clips_6m_leg_at_positive_cap():
    # Only 6m differs (25% raw, clipped to +20%); 1w/1m/3m contribute 0.
    price = _make_price_series(130, last=100, w1=100, m1=100, m3=100, m6=80)
    expected = (0 * 0.10 + 0 * 0.35 + 0 * 0.40 + 20 * 0.15) * (35 / 10)
    assert compute_momentum_score(price) == pytest.approx(expected)


def test_compute_momentum_score_clips_negative_moves():
    # All four legs drop 30%; -15% floor applies to 1m/3m/6m, -5% floor to 1w.
    price = _make_price_series(130, last=70, w1=100, m1=100, m3=100, m6=100)
    expected = (-5 * 0.10 + -15 * 0.35 + -15 * 0.40 + -15 * 0.15) * (35 / 10)
    assert compute_momentum_score(price) == pytest.approx(expected)


def test_compute_momentum_score_handles_insufficient_history():
    price = pd.Series([100.0] * 10)
    assert compute_momentum_score(price) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_momentum_score.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_momentum_score'`

- [ ] **Step 3: Implement `compute_momentum_score` and wire it into `score_asset`**

In `portfolio_app.py`, between line 218 (blank line after the `# SCORING ENGINE` header) and line 219 (`def score_asset(ticker):`), insert:

```python
def compute_momentum_score(price):
    """Weighted multi-timeframe momentum: 1w 10%, 1m 35%, 3m 40%, 6m 15%.
    Returns the scaled point contribution to the 0-100 score (same 3.5x
    scale-up as the old 1m/6m/12m formula, so momentum's overall weight
    relative to fundamentals/volatility/volume in the total score is unchanged)."""
    mom_1w = (price.iloc[-1] / price.iloc[-6])   - 1 if len(price) > 6   else 0
    mom_1m = (price.iloc[-1] / price.iloc[-21])  - 1 if len(price) > 21  else 0
    mom_3m = (price.iloc[-1] / price.iloc[-63])  - 1 if len(price) > 63  else 0
    mom_6m = (price.iloc[-1] / price.iloc[-126]) - 1 if len(price) > 126 else 0

    weighted = (
        float(np.clip(mom_1w * 100, -5,  5))  * 0.10 +
        float(np.clip(mom_1m * 100, -10, 10)) * 0.35 +
        float(np.clip(mom_3m * 100, -15, 18)) * 0.40 +
        float(np.clip(mom_6m * 100, -15, 20)) * 0.15
    )
    return weighted * (35 / 10)
```

Replace the existing momentum block at `portfolio_app.py:227-239`:

```python
    # 1. Multi-timeframe momentum (max ~35 pts)
    mom_1m  = (price.iloc[-1] / price.iloc[-21])  - 1 if len(price) > 21  else 0
    mom_6m  = (price.iloc[-1] / price.iloc[-126]) - 1 if len(price) > 126 else 0
    mom_12m = (price.iloc[-1] / price.iloc[0])    - 1
    momentum_score = (
        float(np.clip(mom_1m  * 100, -10, 10)) * 0.20 +
        float(np.clip(mom_6m  * 100, -15, 20)) * 0.50 +
        float(np.clip(mom_12m * 100, -15, 20)) * 0.30
    ) * (35 / 10)

    # 2. Relative strength vs sector ETF (max 15 pts)
    sector_ret     = get_sector_return_6m(sector)
    relative_score = float(np.clip((float(mom_6m) - sector_ret) * 100, -10, 15))
```

with:

```python
    # 1. Multi-timeframe momentum: 1w/1m/3m/6m weighted (see compute_momentum_score)
    momentum_score = compute_momentum_score(price)

    # 2. Relative strength vs sector ETF (max 15 pts) — uses 6m return
    #    independently of the momentum weighting above.
    mom_6m         = (price.iloc[-1] / price.iloc[-126]) - 1 if len(price) > 126 else 0
    sector_ret     = get_sector_return_6m(sector)
    relative_score = float(np.clip((float(mom_6m) - sector_ret) * 100, -10, 15))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_momentum_score.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_momentum_score.py portfolio_app.py
git commit -m "feat: reweight momentum scoring to 1w/1m/3m/6m"
```

---

### Task 3: RSI failure swing detection

**Files:**
- Create: `tests/test_rsi_failure_swing.py`
- Modify: `portfolio_app.py` (insert new section after `score_asset`, before `target_allocation`, i.e. between lines 298 and 300)

**Interfaces:**
- Produces: `_rsi_series(price: pd.Series, period: int = 14) -> pd.Series`, `_detect_failure_swing(rsi: pd.Series, threshold: float, above: bool) -> bool`, `compute_rsi_failure_swing(price: pd.Series, lookback: int = 20) -> str` returning `"bullish"` / `"bearish"` / `"neutral"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rsi_failure_swing.py`:

```python
import pandas as pd

from portfolio_app import _detect_failure_swing, _rsi_series, compute_rsi_failure_swing


def test_detect_failure_swing_bearish_pattern():
    # Peaks above 70 (75), pulls back below 70, peaks again lower (72), then turns down.
    rsi = pd.Series([50, 60, 75, 74, 65, 68, 72, 70, 65], dtype=float)
    assert _detect_failure_swing(rsi, threshold=70, above=True) is True


def test_detect_failure_swing_no_pattern_when_second_peak_exceeds_first():
    rsi = pd.Series([50, 60, 75, 74, 65, 68, 80, 70, 65], dtype=float)
    assert _detect_failure_swing(rsi, threshold=70, above=True) is False


def test_detect_failure_swing_bullish_pattern():
    # Mirror image: dips below 30 (25), bounces above 30, dips again higher (28), turns up.
    rsi = pd.Series([50, 40, 25, 26, 35, 32, 28, 30, 35], dtype=float)
    assert _detect_failure_swing(rsi, threshold=30, above=False) is True


def test_detect_failure_swing_false_with_no_crossing():
    rsi = pd.Series([50, 55, 52, 58, 54, 56, 53, 57, 55], dtype=float)
    assert _detect_failure_swing(rsi, threshold=70, above=True) is False


def test_rsi_series_uptrend_approaches_100():
    price = pd.Series([100 + i for i in range(30)], dtype=float)  # strictly increasing
    rsi = _rsi_series(price)
    assert rsi.iloc[-1] > 90  # all gains, no losses -> RSI near 100


def test_compute_rsi_failure_swing_neutral_on_insufficient_history():
    price = pd.Series([100.0] * 10)
    assert compute_rsi_failure_swing(price) == "neutral"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_rsi_failure_swing.py -v`
Expected: FAIL with `ImportError: cannot import name '_detect_failure_swing'`

- [ ] **Step 3: Implement RSI + failure swing detection**

In `portfolio_app.py`, between the end of `score_asset` (`portfolio_app.py:297`, `    return score, tier, sector, live_price`) and the blank lines before `def target_allocation(df):` (line 300), insert a new section:

```python
# ─────────────────────────────────────────────────────────────
# TECHNICAL INDICATORS & MOMENTUM SIGNAL
# ─────────────────────────────────────────────────────────────

RSI_PERIOD              = 14
FAILURE_SWING_LOOKBACK  = 20


def _rsi_series(price, period=RSI_PERIOD):
    delta = price.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _detect_failure_swing(rsi, threshold, above):
    """Wilder failure swing: RSI crosses the threshold, pulls back across it,
    pushes again but fails to exceed the first extreme, then turns back."""
    crossed = (rsi > threshold) if above else (rsi < threshold)
    cross_positions = [i for i, c in enumerate(crossed) if c]
    if len(cross_positions) < 2:
        return False

    first_run_end = cross_positions[0]
    for pos in cross_positions[1:]:
        if pos == first_run_end + 1:
            first_run_end = pos
        else:
            break
    first_extreme = rsi.iloc[cross_positions[0]:first_run_end + 1].max() if above \
        else rsi.iloc[cross_positions[0]:first_run_end + 1].min()

    after_first = rsi.iloc[first_run_end + 1:]
    pulled_back_mask = (after_first < threshold) if above else (after_first > threshold)
    if not pulled_back_mask.any():
        return False
    pullback_pos = after_first.index[pulled_back_mask][0]

    second_excursion = rsi.loc[pullback_pos + 1:]
    second_crossed_mask = (second_excursion > threshold) if above else (second_excursion < threshold)
    if not second_crossed_mask.any():
        return False
    second_extreme = second_excursion[second_crossed_mask].max() if above \
        else second_excursion[second_crossed_mask].min()

    failed_to_exceed = (second_extreme < first_extreme) if above else (second_extreme > first_extreme)
    if not failed_to_exceed:
        return False

    turned_back = rsi.iloc[-1] < second_extreme if above else rsi.iloc[-1] > second_extreme
    return bool(turned_back)


def compute_rsi_failure_swing(price, lookback=FAILURE_SWING_LOOKBACK):
    if len(price) < RSI_PERIOD + lookback:
        return "neutral"

    rsi = _rsi_series(price).iloc[-lookback:].reset_index(drop=True)
    if rsi.isna().any():
        return "neutral"

    if _detect_failure_swing(rsi, threshold=70, above=True):
        return "bearish"
    if _detect_failure_swing(rsi, threshold=30, above=False):
        return "bullish"
    return "neutral"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_rsi_failure_swing.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_rsi_failure_swing.py portfolio_app.py
git commit -m "feat: add RSI failure swing detection"
```

---

### Task 4: MACD and 50-day MA signals

**Files:**
- Create: `tests/test_technicals.py`
- Modify: `portfolio_app.py` (append to the "TECHNICAL INDICATORS & MOMENTUM SIGNAL" section added in Task 3)

**Interfaces:**
- Produces: `compute_macd_signal(price: pd.Series) -> str`, `compute_ma50_signal(price: pd.Series) -> str`, both returning `"bullish"` / `"bearish"` / `"neutral"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_technicals.py`:

```python
import pandas as pd

from portfolio_app import compute_ma50_signal, compute_macd_signal


def test_compute_ma50_signal_bullish_when_price_above_average():
    price = pd.Series([100.0] * 49 + [200.0])
    assert compute_ma50_signal(price) == "bullish"


def test_compute_ma50_signal_bearish_when_price_below_average():
    price = pd.Series([200.0] * 49 + [100.0])
    assert compute_ma50_signal(price) == "bearish"


def test_compute_ma50_signal_neutral_on_insufficient_history():
    price = pd.Series([100.0] * 30)
    assert compute_ma50_signal(price) == "neutral"


def test_compute_macd_signal_bullish_on_sustained_uptrend():
    price = pd.Series([100 + i * 2 for i in range(60)], dtype=float)
    assert compute_macd_signal(price) == "bullish"


def test_compute_macd_signal_bearish_on_sustained_downtrend():
    price = pd.Series([200 - i * 2 for i in range(60)], dtype=float)
    assert compute_macd_signal(price) == "bearish"


def test_compute_macd_signal_neutral_on_insufficient_history():
    price = pd.Series([100.0] * 20)
    assert compute_macd_signal(price) == "neutral"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_technicals.py -v`
Expected: FAIL with `ImportError: cannot import name 'compute_ma50_signal'`

- [ ] **Step 3: Implement MACD and 50-MA signals**

In `portfolio_app.py`, append to the end of the "TECHNICAL INDICATORS & MOMENTUM SIGNAL" section (directly after the `compute_rsi_failure_swing` function added in Task 3):

```python
def compute_macd_signal(price):
    if len(price) < 35:
        return "neutral"
    ema12 = price.ewm(span=12, adjust=False).mean()
    ema26 = price.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    return "bullish" if macd_line.iloc[-1] > signal_line.iloc[-1] else "bearish"


def compute_ma50_signal(price):
    if len(price) < 50:
        return "neutral"
    ma50 = price.rolling(50).mean().iloc[-1]
    return "bullish" if price.iloc[-1] > ma50 else "bearish"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_technicals.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_technicals.py portfolio_app.py
git commit -m "feat: add MACD and 50-day MA signal functions"
```

---

### Task 5: `get_technicals()` caching wrapper

**Files:**
- Modify: `tests/test_technicals.py` (append)
- Modify: `portfolio_app.py:74-76` (add `_technicals_cache`), append `get_technicals` to the technical indicators section

**Interfaces:**
- Consumes: `get_price_history(ticker)` (existing, `portfolio_app.py:158`), `compute_macd_signal`, `compute_ma50_signal`, `compute_rsi_failure_swing` (Tasks 3-4).
- Produces: `get_technicals(ticker: str) -> dict` with keys `"macd"`, `"ma50"`, `"rsi_failure_swing"`, each `"bullish"`/`"bearish"`/`"neutral"`. Cached per ticker in `_technicals_cache`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_technicals.py`:

```python
import portfolio_app
from portfolio_app import get_technicals


def test_get_technicals_combines_all_three_indicators_and_caches(monkeypatch):
    portfolio_app._technicals_cache.clear()
    fake_price = pd.Series([100.0 + i for i in range(150)])
    calls = {"count": 0}

    def fake_get_price_history(ticker):
        calls["count"] += 1
        return fake_price

    monkeypatch.setattr(portfolio_app, "get_price_history", fake_get_price_history)

    result = get_technicals("FAKE")
    assert set(result.keys()) == {"macd", "ma50", "rsi_failure_swing"}
    assert result["macd"] in ("bullish", "bearish", "neutral")
    assert result["ma50"] in ("bullish", "bearish", "neutral")
    assert result["rsi_failure_swing"] in ("bullish", "bearish", "neutral")

    get_technicals("FAKE")
    assert calls["count"] == 1  # second call served from cache, no re-fetch
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_technicals.py -v`
Expected: FAIL with `AttributeError: module 'portfolio_app' has no attribute '_technicals_cache'`

- [ ] **Step 3: Implement `get_technicals`**

In `portfolio_app.py:74-76`, replace:

```python
_price_cache      = {}
_info_cache       = {}
_sector_ret_cache = {}
```

with:

```python
_price_cache       = {}
_info_cache        = {}
_sector_ret_cache  = {}
_technicals_cache  = {}
```

Append to the end of the "TECHNICAL INDICATORS & MOMENTUM SIGNAL" section (directly after `compute_ma50_signal` added in Task 4):

```python
def get_technicals(ticker):
    if ticker in _technicals_cache:
        return _technicals_cache[ticker]

    price = get_price_history(ticker)
    result = {
        "macd":              compute_macd_signal(price),
        "ma50":              compute_ma50_signal(price),
        "rsi_failure_swing": compute_rsi_failure_swing(price),
    }
    _technicals_cache[ticker] = result
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_technicals.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_technicals.py portfolio_app.py
git commit -m "feat: add get_technicals caching wrapper"
```

---

### Task 6: Watchlist state persistence

**Files:**
- Create: `tests/test_watchlist_state.py`
- Modify: `portfolio_app.py:41-42` (add `WATCHLIST_FILE`), append new functions after `get_technicals`

**Interfaces:**
- Produces: `load_watchlist_state() -> dict`, `save_watchlist_state(state: dict) -> None`, `is_watchlisted(ticker: str) -> bool`, `flag_watchlisted(ticker: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_watchlist_state.py`:

```python
import portfolio_app
from portfolio_app import flag_watchlisted, is_watchlisted, load_watchlist_state


def test_load_watchlist_state_defaults_to_empty_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    assert load_watchlist_state() == {"flagged": []}


def test_flag_watchlisted_persists_and_is_watchlisted_reflects_it(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    assert is_watchlisted("NVDA") is False
    flag_watchlisted("NVDA")
    assert is_watchlisted("NVDA") is True


def test_flag_watchlisted_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    flag_watchlisted("NVDA")
    flag_watchlisted("NVDA")
    state = load_watchlist_state()
    assert state["flagged"] == ["NVDA"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_watchlist_state.py -v`
Expected: FAIL with `ImportError: cannot import name 'flag_watchlisted'`

- [ ] **Step 3: Implement watchlist persistence**

In `portfolio_app.py:41-42`, replace:

```python
DATA_FILE = "portfolio_data.json"
CSV_FILE  = "portfolio_weights.csv"
```

with:

```python
DATA_FILE      = "portfolio_data.json"
CSV_FILE       = "portfolio_weights.csv"
WATCHLIST_FILE = "watchlist_state.json"
```

Append to the end of the "TECHNICAL INDICATORS & MOMENTUM SIGNAL" section (directly after `get_technicals` added in Task 5):

```python
def load_watchlist_state():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE) as f:
            return json.load(f)
    return {"flagged": []}


def save_watchlist_state(state):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_watchlisted(ticker):
    state = load_watchlist_state()
    return ticker in state.get("flagged", [])


def flag_watchlisted(ticker):
    state   = load_watchlist_state()
    flagged = state.get("flagged", [])
    if ticker not in flagged:
        flagged.append(ticker)
    state["flagged"] = flagged
    save_watchlist_state(state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_watchlist_state.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_watchlist_state.py portfolio_app.py
git commit -m "feat: add watchlist_state.json persistence for repeat-offender tracking"
```

---

### Task 7: `evaluate_momentum_signal()`

**Files:**
- Create: `tests/test_momentum_signal.py`
- Modify: `portfolio_app.py` (append after `flag_watchlisted`)

**Interfaces:**
- Consumes: `is_watchlisted`, `flag_watchlisted` (Task 6).
- Produces: `evaluate_momentum_signal(ticker: str, score: float, technicals: dict) -> str`, returning `"BUY"` / `"FULL_SELL"` / `"TRIM_TO_100"` / `"HOLD"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_momentum_signal.py`:

```python
import portfolio_app
from portfolio_app import evaluate_momentum_signal


def _technicals(macd="neutral", ma50="neutral", rsi_failure_swing="neutral"):
    return {"macd": macd, "ma50": ma50, "rsi_failure_swing": rsi_failure_swing}


def test_buy_when_high_score_and_two_bullish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bullish", ma50="bullish")
    assert evaluate_momentum_signal("NVDA", 75, technicals) == "BUY"


def test_hold_when_high_score_but_only_one_bullish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bullish")
    assert evaluate_momentum_signal("NVDA", 75, technicals) == "HOLD"


def test_trim_to_100_on_first_sell_trigger(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish", ma50="bearish")
    assert evaluate_momentum_signal("CVNA", 20, technicals) == "TRIM_TO_100"
    assert portfolio_app.is_watchlisted("CVNA") is True


def test_full_sell_when_already_watchlisted(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish", ma50="bearish")
    evaluate_momentum_signal("CVNA", 20, technicals)  # first trigger -> TRIM_TO_100
    assert evaluate_momentum_signal("CVNA", 20, technicals) == "FULL_SELL"


def test_hold_when_low_score_but_only_one_bearish(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_app, "WATCHLIST_FILE", str(tmp_path / "watchlist_state.json"))
    technicals = _technicals(macd="bearish")
    assert evaluate_momentum_signal("CVNA", 20, technicals) == "HOLD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_momentum_signal.py -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_momentum_signal'`

- [ ] **Step 3: Implement `evaluate_momentum_signal`**

Append to the end of the "TECHNICAL INDICATORS & MOMENTUM SIGNAL" section (directly after `flag_watchlisted` added in Task 6):

```python
def evaluate_momentum_signal(ticker, score, technicals):
    bullish_count = sum(1 for v in technicals.values() if v == "bullish")
    bearish_count = sum(1 for v in technicals.values() if v == "bearish")

    if score >= 70 and bullish_count >= 2:
        return "BUY"

    if score < 30 and bearish_count >= 2:
        if is_watchlisted(ticker):
            return "FULL_SELL"
        flag_watchlisted(ticker)
        return "TRIM_TO_100"

    return "HOLD"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_momentum_signal.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_momentum_signal.py portfolio_app.py
git commit -m "feat: add evaluate_momentum_signal (BUY/FULL_SELL/TRIM_TO_100/HOLD)"
```

---

### Task 8: Wire `momentum_signal` into `run_scoring()`

**Files:**
- Create: `tests/test_run_scoring.py`
- Modify: `portfolio_app.py:326-353` (the holdings loop in `run_scoring`)

**Interfaces:**
- Consumes: `score_asset` (Task 2, signature unchanged), `get_technicals` (Task 5), `evaluate_momentum_signal` (Task 7).
- Produces: each item in `run_scoring()`'s `positions` list gains a `"momentum_signal"` field.

- [ ] **Step 1: Write the failing test**

Create `tests/test_run_scoring.py`:

```python
import portfolio_app
from portfolio_app import run_scoring


def test_run_scoring_includes_momentum_signal_field(monkeypatch):
    monkeypatch.setattr(portfolio_app, "score_asset",
                         lambda ticker: (75.0, "High", "Technology", 200.0))
    monkeypatch.setattr(portfolio_app, "get_technicals",
                         lambda ticker: {"macd": "bullish", "ma50": "bullish", "rsi_failure_swing": "neutral"})
    monkeypatch.setattr(portfolio_app, "evaluate_momentum_signal",
                         lambda ticker, score, technicals: "BUY")
    monkeypatch.setattr(portfolio_app, "get_soxx_regime", lambda: ("momentum", 0.35))

    holdings = [{"ticker": "NVDA", "shares": "10", "invested": "1000", "type": "main"}]
    result = run_scoring(holdings)

    assert result["positions"][0]["momentum_signal"] == "BUY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_run_scoring.py -v`
Expected: FAIL with `KeyError: 'momentum_signal'`

- [ ] **Step 3: Wire the new fields into the holdings loop**

In `portfolio_app.py:326-353`, replace:

```python
        score, tier, sector, live_price = score_asset(ticker)
        current_value = shares * live_price
        pnl           = current_value - invested
        pnl_pct       = (pnl / invested) if invested > 0 else 0

        info = _info_cache.get(ticker, {})
        rows.append({
            "ticker":        ticker,
            "name":          info.get("name", ticker),
            "shares":        shares,
            "live_price":    live_price,
            "current_value": current_value,
            "invested":      invested,
            "pnl":           pnl,
            "pnl_pct":       pnl_pct,
            "score":         score,
            "tier":          tier,
            "sector":        sector,
            "pos_type":      pos_type,
        })
```

with:

```python
        score, tier, sector, live_price = score_asset(ticker)
        technicals      = get_technicals(ticker)
        momentum_signal = evaluate_momentum_signal(ticker, score, technicals)
        current_value   = shares * live_price
        pnl             = current_value - invested
        pnl_pct         = (pnl / invested) if invested > 0 else 0

        info = _info_cache.get(ticker, {})
        rows.append({
            "ticker":          ticker,
            "name":            info.get("name", ticker),
            "shares":          shares,
            "live_price":      live_price,
            "current_value":   current_value,
            "invested":        invested,
            "pnl":             pnl,
            "pnl_pct":         pnl_pct,
            "score":           score,
            "tier":            tier,
            "sector":          sector,
            "pos_type":        pos_type,
            "momentum_signal": momentum_signal,
        })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/test_run_scoring.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Run the full test suite**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 -m pytest tests/ -v`
Expected: PASS (all tests from Tasks 1-8)

- [ ] **Step 6: Commit**

```bash
git add tests/test_run_scoring.py portfolio_app.py
git commit -m "feat: surface momentum_signal in run_scoring API output"
```

---

### Task 9: Display `momentum_signal` in the frontend

**Files:**
- Modify: `portfolio_app.py:558-561` (CSS), `portfolio_app.py:694-703` (rankings table header), `portfolio_app.py:741-748` (trials table header), `portfolio_app.py:1057-1076` (rankBody row template), `portfolio_app.py:1118-1130` (trialsBody row template)

**Interfaces:**
- Consumes: `momentum_signal` field from Task 8's API response.
- No new Python interfaces — this is HTML/CSS/JS embedded in the `HTML_PAGE` string.

- [ ] **Step 1: Add CSS rules for the new signal states**

In `portfolio_app.py`, after line 561 (`  .HOLD { color: var(--dim); }`), insert:

```css
  .FULL_SELL   { color: var(--red); }
  .TRIM_TO_100 { color: var(--amber); }
```

- [ ] **Step 2: Add a "Momentum" column header to both tables**

Replace `portfolio_app.py:701` (inside the rankings table's `<thead>`):

```html
            <th>Action</th>
```

with:

```html
            <th>Action</th><th>Momentum</th>
```

Replace `portfolio_app.py:746` (inside the trials table's `<thead>`):

```html
            <th>Action</th>
```

with:

```html
            <th>Action</th><th>Momentum</th>
```

- [ ] **Step 3: Add the momentum badge to the rankBody row template**

Replace `portfolio_app.py:1074-1076`:

```js
      <td><span class="action ${p.action}">${p.action}</span></td>
    </tr>`;
  }).join('') || '<tr><td colspan="15" class="empty">No main positions scored</td></tr>';
```

with:

```js
      <td><span class="action ${p.action}">${p.action}</span></td>
      <td><span class="action ${p.momentum_signal}">${p.momentum_signal}</span></td>
    </tr>`;
  }).join('') || '<tr><td colspan="16" class="empty">No main positions scored</td></tr>';
```

- [ ] **Step 4: Add the momentum badge to the trialsBody row template**

Replace `portfolio_app.py:1129-1130`:

```js
    <td><span class="action ${p.action}">${p.action}</span></td>
  </tr>`).join('') : '<tr><td colspan="11" class="empty">No trial positions scored</td></tr>';
```

with:

```js
    <td><span class="action ${p.action}">${p.action}</span></td>
    <td><span class="action ${p.momentum_signal}">${p.momentum_signal}</span></td>
  </tr>`).join('') : '<tr><td colspan="12" class="empty">No trial positions scored</td></tr>';
```

- [ ] **Step 5: Manually verify in the browser**

Run: `cd "/Users/thomasmacbook/Desktop/Pmanager" && python3 portfolio_app.py`

In the browser that opens: load your holdings, click "Score", and confirm:
- The Rankings and Trials tables each show a new "Momentum" column.
- Values are one of BUY / FULL_SELL / TRIM_TO_100 / HOLD, colored per the new CSS rules.
- No layout breakage (table renders correctly, no missing/extra columns).

Stop the server with Ctrl+C when done.

- [ ] **Step 6: Commit**

```bash
git add portfolio_app.py
git commit -m "feat: display momentum_signal column in rankings and trials tables"
```

---

### Task 10: Manual correctness spot-check

**Files:** none (verification only, no code changes)

This is the verification step from the design spec's Testing section — confirming the new momentum math matches a hand calculation on real data before trusting it across the full portfolio.

- [ ] **Step 1: Pick 2-3 tickers from your actual holdings**

Open `portfolio_data.json` and pick 2-3 tickers you currently hold (e.g. one large, liquid name and one smaller/more volatile one).

- [ ] **Step 2: Run a quick interactive check**

```bash
cd "/Users/thomasmacbook/Desktop/Pmanager"
python3 -c "
from portfolio_app import get_price_history, compute_momentum_score

for ticker in ['<TICKER_1>', '<TICKER_2>']:
    price = get_price_history(ticker)
    print(ticker, 'momentum_score =', compute_momentum_score(price))
    print('  1w:',  (price.iloc[-1]/price.iloc[-6]   - 1) * 100, '%')
    print('  1m:',  (price.iloc[-1]/price.iloc[-21]  - 1) * 100, '%')
    print('  3m:',  (price.iloc[-1]/price.iloc[-63]  - 1) * 100, '%')
    print('  6m:',  (price.iloc[-1]/price.iloc[-126] - 1) * 100, '%')
"
```

Replace `<TICKER_1>` / `<TICKER_2>` with your chosen tickers.

- [ ] **Step 3: Hand-verify the math**

For each ticker, manually apply the weights and clip ranges from the Global Constants section to the printed 1w/1m/3m/6m percentages, and confirm your hand-calculated `momentum_score` matches the printed one (within rounding).

- [ ] **Step 4: Confirm in the running app**

Run `python3 portfolio_app.py`, load the same tickers, and confirm the Score and Momentum column values look sane relative to what you just calculated (e.g. a ticker with strong recent gains and bullish technicals should lean toward a high score and BUY, not HOLD or FULL_SELL).

No commit for this task — it's a validation checkpoint, not a code change. If something looks wrong, stop and revisit the relevant earlier task before moving on to Phase 2.

---

## Self-Review

**Spec coverage:** Momentum reweighting (Task 2) ✓. MACD/50-MA/RSI failure swing (Tasks 3-4) ✓. `get_technicals` caching mirroring existing cache pattern (Task 5) ✓. Watchlist state file decoupled from manual Save (Task 6) ✓. Two-sided `momentum_signal` with repeat-offender logic (Task 7) ✓. Wiring into `run_scoring` (Task 8) ✓. `action` SELL→TRIM rename (Task 1) ✓. Frontend display (Task 9) ✓. Correctness spot-check (Task 10) ✓. Error handling (insufficient history → neutral, missing watchlist file → empty dict) is covered inline in Tasks 3, 4, and 6's implementations and tests. Excel import and dated save snapshots were explicitly out of scope for this phase per the design doc.

**Placeholder scan:** No TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `technicals` dicts consistently use keys `macd` / `ma50` / `rsi_failure_swing` with values `"bullish"` / `"bearish"` / `"neutral"` across Tasks 5, 7, and 8's tests. `momentum_signal` values (`BUY`/`FULL_SELL`/`TRIM_TO_100`/`HOLD`) match between Task 7's implementation, Task 8's wiring, and Task 9's CSS class names exactly.
