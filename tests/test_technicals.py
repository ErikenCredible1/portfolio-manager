import pandas as pd

import portfolio_app
from portfolio_app import compute_ma50_signal, compute_macd_signal, get_technicals


def test_compute_ma50_signal_bullish_when_price_above_average():
    price = pd.Series([100.0] * 49 + [200.0])
    assert compute_ma50_signal(price) == "bullish"


def test_compute_ma50_signal_bearish_when_price_below_average():
    price = pd.Series([200.0] * 49 + [100.0])
    assert compute_ma50_signal(price) == "bearish"


def test_compute_ma50_signal_neutral_on_insufficient_history():
    price = pd.Series([100.0] * 30)
    assert compute_ma50_signal(price) == "neutral"


def test_compute_ma50_signal_neutral_when_price_within_1pct_of_average():
    # ma50 = (49*100 + 100.5) / 50 = 100.01; price is 0.49% above it.
    price = pd.Series([100.0] * 49 + [100.5])
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


def test_compute_macd_signal_neutral_on_flat_price():
    # Constant price -> macd_line and signal_line are both exactly 0.
    price = pd.Series([150.0] * 60)
    assert compute_macd_signal(price) == "neutral"


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
