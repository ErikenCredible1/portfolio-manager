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
